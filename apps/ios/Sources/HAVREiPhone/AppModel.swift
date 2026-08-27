#if os(iOS)
import Foundation
import Observation
import AVFoundation
import Speech
import HAVREMobileCore

@MainActor @Observable
final class AppModel {
    var messages: [ChatMessage] = []
    var inboxItems: [ProactiveInboxItem] = []
    var draft = ""
    var privacyClass: PrivacyClass = .localOnly
    var sceneSignal = ""
    var voiceState: VoiceSessionState = .idle
    var isOffline = false
    var statusMessage = "Not enrolled"
    var baseURLText = ""
    var bearerDraft = ""
    var notificationPreviewPolicy: NotificationPreviewPolicy = .none
    var ownerNotificationText = ""
    var replyDrafts = LinkedReplyDrafts()
    private(set) var localStorageHealthy = true
    private(set) var enrollmentReceipt: MobileEnrollmentReceipt?
    private(set) var enrollmentVerified = false
    private(set) var queue: OfflineQueue
    private var client: HAVREAPIClient?
    private let tokenAccount = "havre-owner-api"
    private let synthesizer = AVSpeechSynthesizer()
    private lazy var notificationController = NotificationController { [weak self] action in
        _ = await self?.enqueueDeliveryAction(action)
    }

    init() {
        if FileManager.default.fileExists(atPath: ProtectedStorage.queueURL.path) {
            do {
                queue = try OfflineQueue.decode(Data(contentsOf: ProtectedStorage.queueURL))
            } catch {
                queue = OfflineQueue(); localStorageHealthy = false
                statusMessage = "Protected queue is unreadable; sending is disabled until local erasure."
            }
        } else {
            queue = OfflineQueue()
        }
        if FileManager.default.fileExists(atPath: ProtectedStorage.messageCacheURL.path) {
            do {
                messages = try JSONDecoder.havre.decode(
                    [ChatMessage].self,
                    from: Data(contentsOf: ProtectedStorage.messageCacheURL)
                )
            } catch {
                localStorageHealthy = false
                statusMessage = "Protected cache is unreadable; sending is disabled until local erasure."
            }
        }
        if FileManager.default.fileExists(atPath: ProtectedStorage.enrollmentURL.path) {
            do {
                enrollmentReceipt = try JSONDecoder.havre.decode(
                    MobileEnrollmentReceipt.self,
                    from: Data(contentsOf: ProtectedStorage.enrollmentURL)
                )
            } catch {
                localStorageHealthy = false
                statusMessage = "Enrollment binding is unreadable; local erasure is required."
            }
        }
        if let saved = UserDefaults.standard.string(forKey: "havre.baseURL"),
           enrollmentReceipt != nil, localStorageHealthy {
            baseURLText = saved
            configureClient(from: saved)
        } else if UserDefaults.standard.string(forKey: "havre.baseURL") != nil {
            localStorageHealthy = false
            statusMessage = "Core URL has no verified owner binding; local erasure is required."
        }
        if let raw = UserDefaults.standard.string(forKey: "havre.previewPolicy"),
           let policy = NotificationPreviewPolicy(rawValue: raw) {
            notificationPreviewPolicy = policy
        }
    }

    func enroll() async {
        guard localStorageHealthy else { return }
        guard let url = URL(string: baseURLText), url.scheme == "https", url.host != nil else {
            statusMessage = "Use an HTTPS HAVRE Core URL."
            return
        }
        guard !bearerDraft.isEmpty else {
            statusMessage = "Owner bearer token is required."
            return
        }
        enrollmentVerified = false
        do {
            let probe = HAVREAPIClient(
                baseURL: url, tokenSource: EphemeralTokenSource(value: bearerDraft)
            )
            let receipt = try await probe.enrollmentReceipt()
            try EnrollmentGuard.validate(
                existing: enrollmentReceipt, proposed: receipt,
                hasUnboundPrivateState: (!(await queue.pending()).isEmpty || !messages.isEmpty)
            )
            try ProtectedStorage.writeCache(
                try JSONEncoder.havre.encode(receipt), to: ProtectedStorage.enrollmentURL
            )
            try ProtectedStorage.storeBearer(Data(bearerDraft.utf8), account: tokenAccount)
            UserDefaults.standard.set(url.absoluteString, forKey: "havre.baseURL")
            enrollmentReceipt = receipt; bearerDraft = ""
            configureClient(from: url.absoluteString)
            enrollmentVerified = true
            await reconcile()
            if !isOffline { statusMessage = "Verified existing HAVRE owner and reconciled" }
        } catch EnrollmentBindingError.differentOwnerRequiresErasure {
            statusMessage = "Different HAVRE owner detected; erase local data before switching."
        } catch EnrollmentBindingError.unboundPrivateStateRequiresErasure {
            statusMessage = "Unbound private state exists; erase it before enrollment."
        } catch { statusMessage = "Enrollment verification or protection failed." }
    }

    func send() async {
        guard localStorageHealthy, enrollmentVerified, client != nil else {
            statusMessage = "Verify enrollment before sending"; return
        }
        let text = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return }
        draft = ""
        let item = InteractionDraft(text: text, privacyClass: privacyClass)
        messages.append(ChatMessage(role: .owner, text: text))
        persistMessages()
        guard localStorageHealthy else { return }
        await queue.enqueue(.interaction(item))
        do { try await persistQueue() }
        catch { localStorageHealthy = false; statusMessage = "Queue persistence failed"; return }
        await reconcile()
    }

    func enqueueSceneSignal(_ signal: SceneSignalDraft) async {
        guard localStorageHealthy, enrollmentVerified, client != nil else { return }
        await queue.enqueue(.sceneSignal(signal))
        do { try await persistQueue() }
        catch { localStorageHealthy = false; statusMessage = "Queue persistence failed"; return }
        await reconcile()
    }

    func enqueueSceneTransition(_ transition: SceneTransitionDraft) async {
        guard localStorageHealthy, enrollmentVerified, client != nil else { return }
        await queue.enqueue(.sceneTransition(transition))
        do { try await persistQueue() }
        catch { localStorageHealthy = false; statusMessage = "Queue persistence failed"; return }
        await reconcile()
    }

    func enqueueDeliveryAction(_ action: QueuedDeliveryAction) async -> Bool {
        guard localStorageHealthy, enrollmentVerified, client != nil else { return false }
        await queue.enqueue(.deliveryAction(action))
        do { try await persistQueue() }
        catch {
            localStorageHealthy = false; statusMessage = "Queue persistence failed"
            return false
        }
        await reconcile()
        if !isOffline { await refreshNotificationInbox() }
        return true
    }

    func reconcile() async {
        guard localStorageHealthy, enrollmentVerified, let client else {
            isOffline = true; return
        }
        let report = await OfflineReconciler(transport: client).reconcile(queue)
        for interaction in report.interactions {
            appendAssistantIfMissing(interaction.response)
        }
        if !report.interactions.isEmpty { persistMessages() }
        do { try await persistQueue() }
        catch { localStorageHealthy = false; statusMessage = "Reconciliation persistence failed"; return }
        isOffline = report.blockedEnvelopeID != nil
        statusMessage = isOffline ? "Retry paused at the first unacknowledged event" : "Queue reconciled"
    }

    func eraseLocalData() async {
        do {
            notificationController.clearLocalNotifications()
            try ProtectedStorage.eraseAll(account: tokenAccount)
            UserDefaults.standard.removeObject(forKey: "havre.baseURL")
            UserDefaults.standard.removeObject(forKey: "havre.previewPolicy")
            client = nil; queue = OfflineQueue(); messages = []; inboxItems = []
            enrollmentReceipt = nil
            enrollmentVerified = false
            baseURLText = ""
            notificationPreviewPolicy = .none; ownerNotificationText = ""
            replyDrafts.removeAll()
            localStorageHealthy = true
            statusMessage = "Local cache and credential erased"
        } catch { statusMessage = "Local erasure failed" }
    }

    func requestNotificationPermission() async {
        do {
            try await notificationController.configure()
            statusMessage = "Local notification actions enabled"
        } catch { statusMessage = "Notification permission was not granted" }
    }

    func resume() async {
        guard localStorageHealthy, let client, let enrollmentReceipt else { return }
        enrollmentVerified = false
        do {
            let current = try await client.enrollmentReceipt()
            guard current.coreBindingID == enrollmentReceipt.coreBindingID else {
                self.client = nil
                statusMessage = "HAVRE owner binding changed; reconciliation blocked"
                return
            }
            enrollmentVerified = true
            await reconcile()
        } catch {
            isOffline = true; statusMessage = "Core unavailable; queue retained for retry"
        }
    }

    func refreshNotificationInbox() async {
        guard enrollmentVerified, let client else {
            statusMessage = "Verify enrollment before refreshing notifications"; return
        }
        do {
            let items = try await client.pendingInbox()
            inboxItems = items
            UserDefaults.standard.set(notificationPreviewPolicy.rawValue, forKey: "havre.previewPolicy")
            let result = await notificationController.synchronize(
                items, devicePolicy: notificationPreviewPolicy,
                ownerConfiguredText: ownerNotificationText.isEmpty ? nil : ownerNotificationText
            )
            statusMessage = result.failed == 0
                ? "Refreshed \(items.count) inbox item(s); scheduled \(result.scheduled) authorized notification(s)"
                : "Notification scheduling failed for \(result.failed) item(s)"
        } catch { statusMessage = "Notification inbox refresh failed" }
    }

    func speak(_ text: String) {
        synthesizer.stopSpeaking(at: .immediate)
        synthesizer.speak(AVSpeechUtterance(string: text))
    }

    private func configureClient(from value: String) {
        guard let url = URL(string: value), url.scheme == "https" else { return }
        client = HAVREAPIClient(baseURL: url, tokenSource: KeychainTokenSource(account: tokenAccount))
    }

    private func persistQueue() async throws {
        try ProtectedStorage.writeCache(
            try await queue.encoded(), to: ProtectedStorage.queueURL
        )
    }

    private func persistMessages() {
        do {
            try ProtectedStorage.writeCache(
                try JSONEncoder.havre.encode(messages), to: ProtectedStorage.messageCacheURL
            )
        } catch {
            localStorageHealthy = false; statusMessage = "Message cache persistence failed"
        }
    }

    private func appendAssistantIfMissing(_ response: InteractionResponse) {
        guard !messages.contains(where: { $0.serverEventID == response.assistantEventID }) else {
            return
        }
        messages.append(ChatMessage(
            role: .havre, text: response.content, serverEventID: response.assistantEventID
        ))
    }
}
#endif
