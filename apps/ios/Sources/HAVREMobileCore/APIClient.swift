import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

public protocol BearerTokenSource: Sendable { func token() async throws -> String }

public enum HAVREAPIError: Error, Equatable, Sendable {
    case invalidResponse
    case rejected(status: Int, detail: String)

    public var retryable: Bool {
        switch self {
        case .invalidResponse: true
        case let .rejected(status, _): status == 408 || status == 429 || status >= 500
        }
    }
}

public protocol OfflineTransport: Sendable {
    func send(_ draft: InteractionDraft) async throws -> InteractionResponse
    func submitSceneTransition(_ draft: SceneTransitionDraft) async throws
    func submitSceneSignal(_ draft: SceneSignalDraft) async throws
    func submitDeliveryAction(_ action: QueuedDeliveryAction) async throws -> InteractionResponse?
}

public struct HAVREAPIClient: Sendable {
    public let baseURL: URL
    public let session: URLSession
    public let tokenSource: any BearerTokenSource

    public init(baseURL: URL, session: URLSession = .shared,
                tokenSource: any BearerTokenSource) {
        self.baseURL = baseURL; self.session = session; self.tokenSource = tokenSource
    }

    public func send(_ draft: InteractionDraft) async throws -> InteractionResponse {
        var payload: [String: Any] = [
            "message": draft.text,
            "privacy_class": draft.privacyClass.rawValue,
            "memory_eligible": draft.memoryEligible,
            "client_created_at": ISO8601DateFormatter().string(from: draft.createdAt),
        ]
        if let language = draft.language { payload["language"] = language }
        return try await request(
            path: "/v1/interactions", method: "POST", body: payload,
            idempotencyKey: draft.idempotencyKey
        )
    }

    public func submitSceneSignal(_ draft: SceneSignalDraft) async throws {
        var payload: [String: Any] = [
            "expected_revision": draft.expectedRevision,
            "signal_type": draft.signalType.rawValue,
            "danger": draft.danger.rawValue,
            "avoidance": draft.avoidance.rawValue,
            "energy": draft.energy.rawValue,
            "coercion": draft.coercion.rawValue,
            "goal_alignment": draft.goalAlignment.rawValue,
            "goal_urgency": draft.goalUrgency.rawValue,
            "privacy_class": draft.privacyClass.rawValue,
            "memory_eligible": draft.memoryEligible,
            "occurred_at": ISO8601DateFormatter().string(from: draft.occurredAt),
        ]
        if let note = draft.uncertaintyNote { payload["uncertainty_note"] = note }
        _ = try await rawRequest(
            path: "/v1/scenes/\(draft.sceneSessionID)/signals", method: "POST",
            body: payload, idempotencyKey: draft.idempotencyKey
        )
    }

    public func submitSceneTransition(_ draft: SceneTransitionDraft) async throws {
        var payload: [String: Any] = [
            "expected_revision": draft.expectedRevision,
            "action": draft.action.rawValue,
            "reason": draft.reason,
        ]
        if let terminalStatus = draft.terminalStatus { payload["terminal_status"] = terminalStatus }
        _ = try await rawRequest(
            path: "/v1/scenes/\(draft.sceneSessionID)/transition", method: "POST",
            body: payload, idempotencyKey: draft.idempotencyKey
        )
    }

    public func submitDeliveryAction(_ action: QueuedDeliveryAction) async throws -> InteractionResponse? {
        let reconciliation: DeliveryReconciliation = try await request(
            path: "/v1/proactive/proposals/\(action.link.proposalID)/delivery-reconciliation",
            method: "GET", body: nil, idempotencyKey: nil
        )
        guard reconciliation.deliveryAttemptID == action.link.deliveryAttemptID else {
            throw HAVREAPIError.rejected(status: 409, detail: "delivery linkage mismatch")
        }
        var responseEventID: UUID?
        var interactionResponse: InteractionResponse?
        if action.action == .responded {
            guard let text = action.responseText, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw HAVREAPIError.rejected(status: 422, detail: "response text is required")
            }
            let reply = try await send(InteractionDraft(
                text: text, privacyClass: .localOnly, memoryEligible: false,
                idempotencyKey: "delivery-reply-\(action.idempotencyKey)"
            ))
            responseEventID = reply.userEventID
            interactionResponse = reply
        }
        var payload: [String: Any] = [
            "action_type": action.action.rawValue,
            "reason": action.reason,
            "observed_at": ISO8601DateFormatter().string(from: action.observedAt),
        ]
        if let responseEventID { payload["response_event_id"] = responseEventID.uuidString.lowercased() }
        if let snooze = action.snoozeUntil {
            payload["snooze_until"] = ISO8601DateFormatter().string(from: snooze)
        }
        _ = try await rawRequest(
            path: "/v1/proactive/proposals/\(action.link.proposalID)/actions",
            method: "POST", body: payload, idempotencyKey: action.idempotencyKey
        )
        return interactionResponse
    }

    public func pendingInbox(limit: Int = 100) async throws -> [ProactiveInboxItem] {
        guard 1...100 ~= limit else {
            throw HAVREAPIError.rejected(status: 422, detail: "inbox limit must be between 1 and 100")
        }
        let response: InboxResponse = try await request(
            path: "/v1/proactive/inbox?limit=\(limit)", method: "GET",
            body: nil, idempotencyKey: nil
        )
        return response.items
    }

    public func enrollmentReceipt() async throws -> MobileEnrollmentReceipt {
        try await request(
            path: "/v1/mobile/enrollment", method: "GET",
            body: nil, idempotencyKey: nil
        )
    }

    private func request<T: Decodable>(path: String, method: String,
                                       body: [String: Any]?, idempotencyKey: String?) async throws -> T {
        try JSONDecoder.havre.decode(T.self, from: try await rawRequest(
            path: path, method: method, body: body, idempotencyKey: idempotencyKey
        ))
    }

    private func rawRequest(path: String, method: String, body: [String: Any]?,
                            idempotencyKey: String?) async throws -> Data {
        let pieces = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        var url = baseURL.appendingPathComponent(String(pieces[0].dropFirst()))
        if pieces.count == 2, var components = URLComponents(url: url, resolvingAgainstBaseURL: false) {
            components.percentEncodedQuery = String(pieces[1])
            guard let composed = components.url else { throw HAVREAPIError.invalidResponse }
            url = composed
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        if let body {
            request.httpBody = try JSONSerialization.data(withJSONObject: body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        request.setValue("Bearer \(try await tokenSource.token())", forHTTPHeaderField: "Authorization")
        if let idempotencyKey { request.setValue(idempotencyKey, forHTTPHeaderField: "Idempotency-Key") }
        let (data, response) = try await session.data(for: request)
        guard let http = response as? HTTPURLResponse else { throw HAVREAPIError.invalidResponse }
        guard 200..<300 ~= http.statusCode else {
            throw HAVREAPIError.rejected(
                status: http.statusCode,
                detail: String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            )
        }
        return data
    }
}

extension HAVREAPIClient: OfflineTransport {}

private struct DeliveryReconciliation: Decodable {
    let deliveryAttemptID: UUID?
    enum CodingKeys: String, CodingKey { case deliveryAttemptID = "delivery_attempt_id" }
}

private struct InboxResponse: Decodable {
    let schemaVersion: Int
    let items: [ProactiveInboxItem]
    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case items
    }
}
