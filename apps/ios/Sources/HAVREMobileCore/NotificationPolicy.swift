import Foundation

public enum NotificationPolicy {
    public static func authorizedVisibleBody(
        corePolicy: NotificationPreviewPolicy,
        devicePolicy: NotificationPreviewPolicy,
        privacyClass: PrivacyClass,
        fullText: String,
        corePreviewText: String? = nil,
        ownerConfiguredText: String? = nil
    ) -> String? {
        guard corePolicy != .none else { return nil }
        let effective = devicePolicy == .full && corePolicy == .genericPrivate
            ? NotificationPreviewPolicy.genericPrivate : devicePolicy
        if effective == .genericPrivate, let corePreviewText { return corePreviewText }
        return visibleBody(
            policy: effective, privacyClass: privacyClass, fullText: fullText,
            ownerConfiguredText: ownerConfiguredText
        )
    }

    public static func visibleBody(
        policy: NotificationPreviewPolicy,
        privacyClass: PrivacyClass,
        fullText: String,
        ownerConfiguredText: String? = nil
    ) -> String? {
        switch policy {
        case .none:
            return nil
        case .genericPrivate:
            return "HAVRE has something for you."
        case .ownerConfigured:
            return ownerConfiguredText
        case .full:
            guard privacyClass == .normal else { return nil }
            return fullText
        }
    }
}

public enum VoiceSessionState: Equatable, Sendable {
    case idle, requestingPermission, listening, transcribing, ready(String), failed
}

public struct VoiceSessionMachine: Sendable {
    public private(set) var state: VoiceSessionState = .idle
    public init() {}
    public mutating func ownerTappedStart() {
        if state == .idle || state == .failed {
            state = .requestingPermission
        } else if case .ready = state {
            state = .requestingPermission
        }
    }
    public mutating func permissionResult(granted: Bool) {
        guard state == .requestingPermission else { return }
        state = granted ? .listening : .failed
    }
    public mutating func ownerTappedStop() { if state == .listening { state = .transcribing } }
    public mutating func transcript(_ text: String) {
        guard state == .transcribing else { return }
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        state = trimmed.isEmpty ? .failed : .ready(trimmed)
    }
    public mutating func fail() { state = .failed }
    public mutating func reset() { state = .idle }
}
