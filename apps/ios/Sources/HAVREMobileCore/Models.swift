import Foundation

public enum PrivacyClass: String, Codable, Sendable, CaseIterable {
    case normal = "NORMAL"
    case `private` = "PRIVATE"
    case highlyPrivate = "HIGHLY_PRIVATE"
    case localOnly = "LOCAL_ONLY"
}

public struct InteractionDraft: Codable, Equatable, Sendable, Identifiable {
    public let id: UUID
    public let text: String
    public let privacyClass: PrivacyClass
    public let memoryEligible: Bool
    public let language: String?
    public let createdAt: Date
    public let idempotencyKey: String

    public init(
        id: UUID = UUID(), text: String, privacyClass: PrivacyClass,
        memoryEligible: Bool = false, language: String? = nil,
        createdAt: Date = Date(),
        idempotencyKey: String = UUID().uuidString.lowercased()
    ) {
        self.id = id
        self.text = text
        self.privacyClass = privacyClass
        self.memoryEligible = memoryEligible
        self.language = language
        self.createdAt = createdAt
        self.idempotencyKey = idempotencyKey
    }
}

public struct ChatMessage: Codable, Equatable, Sendable, Identifiable {
    public enum Role: String, Codable, Sendable { case owner, havre }
    public let id: UUID
    public let role: Role
    public let text: String
    public let createdAt: Date
    public let serverEventID: UUID?

    public init(
        id: UUID = UUID(), role: Role, text: String, createdAt: Date = Date(),
        serverEventID: UUID? = nil
    ) {
        self.id = id; self.role = role; self.text = text; self.createdAt = createdAt
        self.serverEventID = serverEventID
    }
}

public struct InteractionResponse: Codable, Equatable, Sendable {
    public let requestID: UUID
    public let userEventID: UUID
    public let assistantEventID: UUID
    public let content: String

    public init(requestID: UUID, userEventID: UUID, assistantEventID: UUID, content: String) {
        self.requestID = requestID; self.userEventID = userEventID
        self.assistantEventID = assistantEventID; self.content = content
    }

    enum CodingKeys: String, CodingKey {
        case requestID = "request_id"
        case userEventID = "user_event_id"
        case assistantEventID = "assistant_event_id"
        case content
    }
}

public struct MobileEnrollmentReceipt: Codable, Equatable, Sendable {
    public let schemaVersion: Int
    public let ownerID: UUID
    public let coreBindingID: String
    public let constitutionVersionID: String
    public let identityVersionID: String
    public let valuesVersionID: String
    public let governanceVersion: String

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case ownerID = "owner_id"
        case coreBindingID = "core_binding_id"
        case constitutionVersionID = "constitution_version_id"
        case identityVersionID = "identity_version_id"
        case valuesVersionID = "values_version_id"
        case governanceVersion = "governance_version"
    }
}

public enum EnrollmentBindingError: Error, Equatable, Sendable {
    case invalidReceipt
    case differentOwnerRequiresErasure
    case unboundPrivateStateRequiresErasure
}

public enum EnrollmentGuard {
    public static func validate(
        existing: MobileEnrollmentReceipt?, proposed: MobileEnrollmentReceipt,
        hasUnboundPrivateState: Bool
    ) throws {
        guard proposed.coreBindingID == "owner:\(proposed.ownerID.uuidString.lowercased())" else {
            throw EnrollmentBindingError.invalidReceipt
        }
        if let existing, existing.coreBindingID != proposed.coreBindingID {
            throw EnrollmentBindingError.differentOwnerRequiresErasure
        }
        if existing == nil, hasUnboundPrivateState {
            throw EnrollmentBindingError.unboundPrivateStateRequiresErasure
        }
    }
}

public enum ScenePhase: String, Codable, Sendable, CaseIterable {
    case before, during, after
}

public enum SceneTransitionAction: String, Codable, Sendable, CaseIterable {
    case start, pause, resume, after, close
}

public struct SceneTransitionDraft: Codable, Equatable, Sendable {
    public let sceneSessionID: UUID
    public let expectedRevision: Int
    public let action: SceneTransitionAction
    public let reason: String
    public let terminalStatus: String?
    public let idempotencyKey: String

    public init(
        sceneSessionID: UUID, expectedRevision: Int, action: SceneTransitionAction,
        reason: String, terminalStatus: String? = nil,
        idempotencyKey: String = UUID().uuidString.lowercased()
    ) {
        self.sceneSessionID = sceneSessionID; self.expectedRevision = expectedRevision
        self.action = action; self.reason = reason; self.terminalStatus = terminalStatus
        self.idempotencyKey = idempotencyKey
    }
}

public enum SceneSignalType: String, Codable, Sendable, CaseIterable {
    case anxious, avoidanceUrge = "avoidance_urge", frozen
    case unsureNextStep = "unsure_next_step", needHelp = "need_help"
}
public enum DangerAssessment: String, Codable, Sendable, CaseIterable {
    case low, uncertain, plausible, immediate
}
public enum AvoidanceAssessment: String, Codable, Sendable, CaseIterable {
    case low, present, high, unknown
}
public enum EnergyAssessment: String, Codable, Sendable, CaseIterable {
    case adequate, low, exhausted, unknown
}
public enum CoercionAssessment: String, Codable, Sendable, CaseIterable {
    case absent, uncertain, present
}
public enum GoalAlignment: String, Codable, Sendable, CaseIterable {
    case activeMeaningful = "active_meaningful", unclear, noActiveGoal = "no_active_goal"
}
public enum GoalUrgency: String, Codable, Sendable, CaseIterable {
    case low, normal, urgent, unknown
}

public struct SceneSignalDraft: Codable, Equatable, Sendable {
    public let sceneSessionID: UUID
    public let expectedRevision: Int
    public let signalType: SceneSignalType
    public let danger: DangerAssessment
    public let avoidance: AvoidanceAssessment
    public let energy: EnergyAssessment
    public let coercion: CoercionAssessment
    public let goalAlignment: GoalAlignment
    public let goalUrgency: GoalUrgency
    public let privacyClass: PrivacyClass
    public let memoryEligible: Bool
    public let occurredAt: Date
    public let uncertaintyNote: String?
    public let idempotencyKey: String

    public init(
        sceneSessionID: UUID, expectedRevision: Int, signalType: SceneSignalType,
        danger: DangerAssessment = .uncertain,
        avoidance: AvoidanceAssessment = .unknown,
        energy: EnergyAssessment = .unknown,
        coercion: CoercionAssessment = .uncertain,
        goalAlignment: GoalAlignment = .unclear,
        goalUrgency: GoalUrgency = .unknown,
        privacyClass: PrivacyClass = .private,
        memoryEligible: Bool = false,
        occurredAt: Date = Date(), uncertaintyNote: String? = nil,
                idempotencyKey: String = UUID().uuidString.lowercased()) {
        self.sceneSessionID = sceneSessionID
        self.expectedRevision = expectedRevision
        self.signalType = signalType
        self.danger = danger
        self.avoidance = avoidance
        self.energy = energy
        self.coercion = coercion
        self.goalAlignment = goalAlignment
        self.goalUrgency = goalUrgency
        self.privacyClass = privacyClass
        self.memoryEligible = memoryEligible
        self.occurredAt = occurredAt
        self.uncertaintyNote = uncertaintyNote
        self.idempotencyKey = idempotencyKey
    }
}

public enum NotificationPreviewPolicy: String, Codable, Sendable, CaseIterable {
    case full, genericPrivate = "generic_private", none
    case ownerConfigured = "owner_configured"
}

public struct DeliveryLink: Codable, Equatable, Sendable {
    public let proposalID: UUID
    public let deliveryAttemptID: UUID
    public init(proposalID: UUID, deliveryAttemptID: UUID) {
        self.proposalID = proposalID; self.deliveryAttemptID = deliveryAttemptID
    }
}

public struct NotificationLinkPayload: Equatable, Sendable {
    public let link: DeliveryLink
    public init(values: [String: String]) throws {
        guard let proposal = values["proposal_id"].flatMap(UUID.init(uuidString:)),
              let attempt = values["delivery_attempt_id"].flatMap(UUID.init(uuidString:)) else {
            throw NotificationLinkError.missingExactLink
        }
        link = DeliveryLink(proposalID: proposal, deliveryAttemptID: attempt)
    }
}

public struct ProactiveInboxItem: Codable, Equatable, Sendable, Identifiable {
    public let schemaVersion: Int
    public let inboxMessageID: UUID
    public let proposalID: UUID
    public let deliveryAttemptID: UUID
    public let assistantEventID: UUID
    public let contentText: String?
    public let previewPolicy: NotificationPreviewPolicy
    public let previewText: String?
    public let privacyClass: PrivacyClass
    public let visibleAt: Date
    public let simulationOnly: Bool
    public let externalDeliveryAuthorized: Bool
    public var id: UUID { inboxMessageID }

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case inboxMessageID = "inbox_message_id"
        case proposalID = "proposal_id"
        case deliveryAttemptID = "delivery_attempt_id"
        case assistantEventID = "assistant_event_id"
        case contentText = "content_text"
        case previewPolicy = "preview_policy"
        case previewText = "preview_text"
        case privacyClass = "privacy_class"
        case visibleAt = "visible_at"
        case simulationOnly = "simulation_only"
        case externalDeliveryAuthorized = "external_delivery_authorized"
    }
}

public enum NotificationLinkError: Error, Equatable, Sendable {
    case missingExactLink
}

public enum DeliveryAction: String, Codable, Sendable {
    case responded, dismissed, snoozed, stopped
}

public struct QueuedDeliveryAction: Codable, Equatable, Sendable, Identifiable {
    public let id: UUID
    public let link: DeliveryLink
    public let action: DeliveryAction
    public let responseText: String?
    public let snoozeUntil: Date?
    public let reason: String
    public let observedAt: Date
    public let idempotencyKey: String

    public init(id: UUID = UUID(), link: DeliveryLink, action: DeliveryAction,
                responseText: String? = nil, snoozeUntil: Date? = nil,
                reason: String = "owner action from iPhone", observedAt: Date = Date(),
                idempotencyKey: String = UUID().uuidString.lowercased()) {
        self.id = id; self.link = link; self.action = action
        self.responseText = responseText; self.snoozeUntil = snoozeUntil
        self.reason = reason; self.observedAt = observedAt
        self.idempotencyKey = idempotencyKey
    }
}

public struct LinkedReplyDrafts: Equatable, Sendable {
    private var values: [UUID: String] = [:]
    public init() {}
    public func text(for deliveryAttemptID: UUID) -> String {
        values[deliveryAttemptID] ?? ""
    }
    public mutating func set(_ text: String, for deliveryAttemptID: UUID) {
        values[deliveryAttemptID] = text
    }
    public mutating func take(for deliveryAttemptID: UUID) -> String {
        values.removeValue(forKey: deliveryAttemptID) ?? ""
    }
    public mutating func removeAll() { values.removeAll() }
}

public struct ProtectedCachePolicy: Equatable, Sendable {
    public let fileProtection: String
    public let excludesFromBackup: Bool
    public let storesBearerInKeychainOnly: Bool
    public static let required = ProtectedCachePolicy(
        fileProtection: "completeUntilFirstUserAuthentication",
        excludesFromBackup: true,
        storesBearerInKeychainOnly: true
    )
}
