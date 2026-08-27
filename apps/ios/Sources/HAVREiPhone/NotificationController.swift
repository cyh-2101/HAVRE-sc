#if os(iOS)
import UserNotifications
import HAVREMobileCore

@MainActor
final class NotificationController: NSObject, UNUserNotificationCenterDelegate {
    static let category = "HAVRE_PROACTIVE"
    private let actionSink: (QueuedDeliveryAction) async -> Void

    init(actionSink: @escaping (QueuedDeliveryAction) async -> Void) {
        self.actionSink = actionSink
    }

    func configure() async throws {
        let center = UNUserNotificationCenter.current()
        center.delegate = self
        center.setNotificationCategories([UNNotificationCategory(
            identifier: Self.category,
            actions: [
                UNTextInputNotificationAction(identifier: "responded", title: "Reply"),
                UNNotificationAction(identifier: "snoozed", title: "Snooze"),
                UNNotificationAction(identifier: "stopped", title: "Stop"),
            ], intentIdentifiers: [], options: [.customDismissAction]
        )])
        guard try await center.requestAuthorization(options: [.alert, .sound, .badge]) else {
            throw NotificationPermissionError.denied
        }
    }

    func synchronize(
        _ items: [ProactiveInboxItem], devicePolicy: NotificationPreviewPolicy,
        ownerConfiguredText: String?
    ) async -> (scheduled: Int, failed: Int) {
        let center = UNUserNotificationCenter.current()
        clearLocalNotifications()
        var scheduled = 0, failed = 0
        for item in items {
            guard !item.simulationOnly, item.externalDeliveryAuthorized else { continue }
            guard let body = NotificationPolicy.authorizedVisibleBody(
                corePolicy: item.previewPolicy, devicePolicy: devicePolicy,
                privacyClass: item.privacyClass, fullText: item.contentText ?? "",
                corePreviewText: item.previewText,
                ownerConfiguredText: ownerConfiguredText
            ) else { continue }
            let content = UNMutableNotificationContent()
            content.title = "HAVRE"
            content.body = body
            content.categoryIdentifier = Self.category
            content.userInfo = [
                "proposal_id": item.proposalID.uuidString.lowercased(),
                "delivery_attempt_id": item.deliveryAttemptID.uuidString.lowercased(),
            ]
            let request = UNNotificationRequest(
                identifier: item.deliveryAttemptID.uuidString.lowercased(),
                content: content, trigger: nil
            )
            do { try await center.add(request); scheduled += 1 }
            catch { failed += 1 }
        }
        return (scheduled, failed)
    }

    func clearLocalNotifications() {
        let center = UNUserNotificationCenter.current()
        center.removeAllDeliveredNotifications()
        center.removeAllPendingNotificationRequests()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse) async {
        let values = response.notification.request.content.userInfo.reduce(into: [String: String]()) {
            if let value = $1.value as? String { $0[String(describing: $1.key)] = value }
        }
        guard let link = try? NotificationLinkPayload(values: values).link else { return }
        let now = Date()
        let action: QueuedDeliveryAction
        switch response.actionIdentifier {
        case "responded":
            guard let text = (response as? UNTextInputNotificationResponse)?.userText else { return }
            action = QueuedDeliveryAction(link: link, action: .responded, responseText: text)
        case "snoozed":
            action = QueuedDeliveryAction(
                link: link, action: .snoozed, snoozeUntil: now.addingTimeInterval(3600)
            )
        case "stopped": action = QueuedDeliveryAction(link: link, action: .stopped)
        case UNNotificationDismissActionIdentifier:
            action = QueuedDeliveryAction(link: link, action: .dismissed)
        default: return
        }
        await actionSink(action)
    }
}

private enum NotificationPermissionError: Error { case denied }
#endif
