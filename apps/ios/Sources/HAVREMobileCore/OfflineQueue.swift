import Foundation

public struct OfflineEnvelope: Codable, Equatable, Sendable, Identifiable {
    public enum Payload: Codable, Equatable, Sendable {
        case interaction(InteractionDraft)
        case sceneTransition(SceneTransitionDraft)
        case sceneSignal(SceneSignalDraft)
        case deliveryAction(QueuedDeliveryAction)
    }
    public let id: UUID
    public let sequence: UInt64
    public let payload: Payload
    public let enqueuedAt: Date
}

public actor OfflineQueue {
    private var entries: [OfflineEnvelope]
    private var nextSequence: UInt64

    public init(entries: [OfflineEnvelope] = []) {
        self.entries = entries.sorted { $0.sequence < $1.sequence }
        self.nextSequence = (entries.map(\.sequence).max() ?? 0) + 1
    }

    @discardableResult
    public func enqueue(_ payload: OfflineEnvelope.Payload, now: Date = Date()) -> OfflineEnvelope {
        let envelope = OfflineEnvelope(
            id: UUID(), sequence: nextSequence, payload: payload, enqueuedAt: now
        )
        nextSequence += 1
        entries.append(envelope)
        return envelope
    }

    public func pending() -> [OfflineEnvelope] { entries }

    public func acknowledge(id: UUID) {
        entries.removeAll { $0.id == id }
    }

    public func encoded() throws -> Data {
        try JSONEncoder.havre.encode(entries)
    }

    public static func decode(_ data: Data) throws -> OfflineQueue {
        OfflineQueue(entries: try JSONDecoder.havre.decode([OfflineEnvelope].self, from: data))
    }
}

public struct ReconciliationReport: Equatable, Sendable {
    public let acknowledged: [UUID]
    public let interactions: [ReconciledInteraction]
    public let blockedEnvelopeID: UUID?
    public init(
        acknowledged: [UUID], interactions: [ReconciledInteraction],
        blockedEnvelopeID: UUID?
    ) {
        self.acknowledged = acknowledged; self.interactions = interactions
        self.blockedEnvelopeID = blockedEnvelopeID
    }
}

public struct ReconciledInteraction: Equatable, Sendable {
    public let envelopeID: UUID
    public let response: InteractionResponse
    public init(envelopeID: UUID, response: InteractionResponse) {
        self.envelopeID = envelopeID; self.response = response
    }
}

public struct OfflineReconciler: Sendable {
    public let transport: any OfflineTransport
    public init(transport: any OfflineTransport) { self.transport = transport }

    public func reconcile(_ queue: OfflineQueue) async -> ReconciliationReport {
        var acknowledged: [UUID] = []
        var interactions: [ReconciledInteraction] = []
        for envelope in await queue.pending() {
            do {
                switch envelope.payload {
                case let .interaction(draft):
                    interactions.append(ReconciledInteraction(
                        envelopeID: envelope.id, response: try await transport.send(draft)
                    ))
                case let .sceneTransition(draft): try await transport.submitSceneTransition(draft)
                case let .sceneSignal(draft): try await transport.submitSceneSignal(draft)
                case let .deliveryAction(action):
                    if let response = try await transport.submitDeliveryAction(action) {
                        interactions.append(ReconciledInteraction(
                            envelopeID: envelope.id, response: response
                        ))
                    }
                }
                await queue.acknowledge(id: envelope.id)
                acknowledged.append(envelope.id)
            } catch {
                return ReconciliationReport(
                    acknowledged: acknowledged, interactions: interactions,
                    blockedEnvelopeID: envelope.id
                )
            }
        }
        return ReconciliationReport(
            acknowledged: acknowledged, interactions: interactions, blockedEnvelopeID: nil
        )
    }
}

public extension JSONEncoder {
    static var havre: JSONEncoder {
        let encoder = JSONEncoder(); encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys]; return encoder
    }
}

public extension JSONDecoder {
    static var havre: JSONDecoder {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { value in
            let container = try value.singleValueContainer()
            let text = try container.decode(String.self)
            for options: ISO8601DateFormatter.Options in [
                [.withInternetDateTime, .withFractionalSeconds],
                [.withInternetDateTime],
            ] {
                let formatter = ISO8601DateFormatter(); formatter.formatOptions = options
                if let date = formatter.date(from: text) { return date }
            }
            throw DecodingError.dataCorruptedError(
                in: container, debugDescription: "expected an RFC3339 timestamp"
            )
        }
        return decoder
    }
}
