import XCTest
@testable import HAVREMobileCore
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif

final class HAVREMobileCoreTests: XCTestCase {
    func testQueuePreservesOrderAndAcknowledgesExactlyOneEnvelope() async throws {
        let queue = OfflineQueue()
        let first = await queue.enqueue(.interaction(InteractionDraft(text: "one", privacyClass: .localOnly)))
        let second = await queue.enqueue(.interaction(InteractionDraft(text: "two", privacyClass: .private)))
        let firstPending = await queue.pending().map(\.id)
        XCTAssertEqual(firstPending, [first.id, second.id])
        await queue.acknowledge(id: first.id)
        let secondPending = await queue.pending().map(\.id)
        XCTAssertEqual(secondPending, [second.id])
        let restored = try OfflineQueue.decode(await queue.encoded())
        let restoredPending = await restored.pending().map(\.id)
        XCTAssertEqual(restoredPending, [second.id])
    }

    func testPreviewFailsClosedForPrivateContent() {
        XCTAssertNil(NotificationPolicy.visibleBody(policy: .none, privacyClass: .normal, fullText: "x"))
        XCTAssertNil(NotificationPolicy.visibleBody(policy: .full, privacyClass: .private, fullText: "secret"))
        XCTAssertEqual(NotificationPolicy.visibleBody(policy: .genericPrivate, privacyClass: .highlyPrivate, fullText: "secret"), "HAVRE has something for you.")
        XCTAssertEqual(NotificationPolicy.visibleBody(
            policy: .ownerConfigured, privacyClass: .localOnly, fullText: "secret",
            ownerConfiguredText: "Check in when ready."
        ), "Check in when ready.")
        XCTAssertNil(NotificationPolicy.authorizedVisibleBody(
            corePolicy: .none, devicePolicy: .ownerConfigured,
            privacyClass: .localOnly, fullText: "secret",
            ownerConfiguredText: "local choice"
        ))
        XCTAssertEqual(NotificationPolicy.authorizedVisibleBody(
            corePolicy: .genericPrivate, devicePolicy: .full,
            privacyClass: .normal, fullText: "full content",
            corePreviewText: "Core generic"
        ), "Core generic")
    }

    func testDeliveryActionRetainsOriginalProposalAndAttempt() {
        let link = DeliveryLink(proposalID: UUID(), deliveryAttemptID: UUID())
        let action = QueuedDeliveryAction(link: link, action: .snoozed)
        XCTAssertEqual(action.link, link)
    }

    func testReplyDraftsRemainBoundToExactDeliveryAttempt() {
        let first = UUID(), second = UUID()
        var drafts = LinkedReplyDrafts()
        drafts.set("reply to first", for: first)
        drafts.set("reply to second", for: second)
        XCTAssertEqual(drafts.take(for: second), "reply to second")
        XCTAssertEqual(drafts.text(for: first), "reply to first")
        XCTAssertEqual(drafts.text(for: second), "")
    }

    func testNotificationPayloadRequiresBothOriginalIdentities() throws {
        let proposal = UUID(), attempt = UUID()
        let payload = try NotificationLinkPayload(values: [
            "proposal_id": proposal.uuidString,
            "delivery_attempt_id": attempt.uuidString,
        ])
        XCTAssertEqual(payload.link, DeliveryLink(proposalID: proposal, deliveryAttemptID: attempt))
        XCTAssertThrowsError(try NotificationLinkPayload(values: [
            "proposal_id": proposal.uuidString,
        ]))
    }

    func testInboxProjectionRetainsCoreDeliveryAuthorizationFlags() throws {
        let object: [String: Any] = [
            "schema_version": 1,
            "inbox_message_id": UUID().uuidString,
            "proposal_id": UUID().uuidString,
            "delivery_attempt_id": UUID().uuidString,
            "assistant_event_id": UUID().uuidString,
            "content_text": NSNull(),
            "preview_policy": "generic_private",
            "preview_text": "generic preview",
            "privacy_class": "LOCAL_ONLY",
            "visible_at": "2026-08-22T00:00:00.123456+00:00",
            "simulation_only": true,
            "external_delivery_authorized": false,
        ]
        let item = try JSONDecoder.havre.decode(
            ProactiveInboxItem.self,
            from: JSONSerialization.data(withJSONObject: object)
        )
        XCTAssertTrue(item.simulationOnly)
        XCTAssertFalse(item.externalDeliveryAuthorized)
        XCTAssertNil(item.contentText)
    }

    func testVoiceCannotStartWithoutOwnerTap() {
        var voice = VoiceSessionMachine()
        voice.permissionResult(granted: true)
        XCTAssertEqual(voice.state, .idle)
        voice.ownerTappedStart(); voice.permissionResult(granted: true)
        voice.ownerTappedStop(); voice.transcript("hello")
        XCTAssertEqual(voice.state, .ready("hello"))
        voice.ownerTappedStart()
        XCTAssertEqual(voice.state, .requestingPermission)
        voice.permissionResult(granted: true)
        voice.ownerTappedStop(); voice.transcript("   ")
        XCTAssertEqual(voice.state, .failed)
        voice.ownerTappedStart()
        XCTAssertEqual(voice.state, .requestingPermission)
    }

    func testProtectedCachePolicyIsDeviceBound() {
        XCTAssertEqual(ProtectedCachePolicy.required.fileProtection, "completeUntilFirstUserAuthentication")
        XCTAssertTrue(ProtectedCachePolicy.required.excludesFromBackup)
        XCTAssertTrue(ProtectedCachePolicy.required.storesBearerInKeychainOnly)
    }

    func testHTTPClientUsesExistingInteractionContract() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let session = URLSession(configuration: configuration)
        let requestID = UUID(), userEventID = UUID(), assistantEventID = UUID()
        URLProtocolStub.handler = { request in
            XCTAssertEqual(request.url?.path, "/v1/interactions")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Idempotency-Key"), "stable-key")
            XCTAssertEqual(request.value(forHTTPHeaderField: "Authorization"), "Bearer owner-token")
            let body = try XCTUnwrap(request.httpBody)
            let object = try XCTUnwrap(
                JSONSerialization.jsonObject(with: body) as? [String: Any]
            )
            XCTAssertEqual(object["message"] as? String, "hello")
            XCTAssertEqual(object["privacy_class"] as? String, "LOCAL_ONLY")
            XCTAssertEqual(object["memory_eligible"] as? Bool, false)
            let data = try JSONSerialization.data(withJSONObject: [
                "request_id": requestID.uuidString,
                "user_event_id": userEventID.uuidString,
                "assistant_event_id": assistantEventID.uuidString,
                "content": "hi",
            ])
            return (HTTPURLResponse(
                url: try XCTUnwrap(request.url), statusCode: 200,
                httpVersion: nil, headerFields: nil
            )!, data)
        }
        defer { URLProtocolStub.handler = nil }
        let client = HAVREAPIClient(
            baseURL: URL(string: "https://owner.example")!, session: session,
            tokenSource: FixedTokenSource()
        )
        let result = try await client.send(InteractionDraft(
            text: "hello", privacyClass: .localOnly, memoryEligible: false,
            idempotencyKey: "stable-key"
        ))
        XCTAssertEqual(result.requestID, requestID)
        XCTAssertEqual(result.userEventID, userEventID)
        XCTAssertEqual(result.assistantEventID, assistantEventID)
        XCTAssertEqual(result.content, "hi")
    }

    func testEnrollmentBindingRejectsOwnerSwitchAndUnboundPrivateState() throws {
        func receipt(owner: UUID) -> MobileEnrollmentReceipt {
            MobileEnrollmentReceipt(
                schemaVersion: 1, ownerID: owner,
                coreBindingID: "owner:\(owner.uuidString.lowercased())",
                constitutionVersionID: "constitution-v1",
                identityVersionID: "identity-v1", valuesVersionID: "values-v1",
                governanceVersion: "governance-v1"
            )
        }
        let first = receipt(owner: UUID()), same = first, other = receipt(owner: UUID())
        XCTAssertNoThrow(try EnrollmentGuard.validate(
            existing: first, proposed: same, hasUnboundPrivateState: true
        ))
        XCTAssertThrowsError(try EnrollmentGuard.validate(
            existing: first, proposed: other, hasUnboundPrivateState: false
        ))
        XCTAssertThrowsError(try EnrollmentGuard.validate(
            existing: nil, proposed: first, hasUnboundPrivateState: true
        ))
        let invalid = MobileEnrollmentReceipt(
            schemaVersion: 1, ownerID: first.ownerID, coreBindingID: "owner:\(UUID())",
            constitutionVersionID: "constitution-v1", identityVersionID: "identity-v1",
            valuesVersionID: "values-v1", governanceVersion: "governance-v1"
        )
        XCTAssertThrowsError(try EnrollmentGuard.validate(
            existing: nil, proposed: invalid, hasUnboundPrivateState: false
        ))
    }

    func testDeliveryReplyVerifiesAttemptAndLinksOwnerEvent() async throws {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [URLProtocolStub.self]
        let proposal = UUID(), attempt = UUID(), userEvent = UUID(), assistantEvent = UUID()
        URLProtocolStub.requestNumber = 0
        URLProtocolStub.handler = { request in
            URLProtocolStub.requestNumber += 1
            let number = URLProtocolStub.requestNumber
            let object: [String: Any]
            switch number {
            case 1:
                XCTAssertTrue(request.url?.path.hasSuffix("/delivery-reconciliation") == true)
                object = ["delivery_attempt_id": attempt.uuidString]
            case 2:
                XCTAssertEqual(request.url?.path, "/v1/interactions")
                object = [
                    "request_id": UUID().uuidString,
                    "user_event_id": userEvent.uuidString,
                    "assistant_event_id": assistantEvent.uuidString,
                    "content": "linked reply",
                ]
            case 3:
                XCTAssertTrue(request.url?.path.hasSuffix("/actions") == true)
                let body = try XCTUnwrap(request.httpBody)
                let submitted = try XCTUnwrap(
                    JSONSerialization.jsonObject(with: body) as? [String: Any]
                )
                XCTAssertEqual(submitted["response_event_id"] as? String, userEvent.uuidString.lowercased())
                XCTAssertEqual(submitted["action_type"] as? String, "responded")
                object = [:]
            default:
                XCTFail("unexpected extra request")
                object = [:]
            }
            let data = try JSONSerialization.data(withJSONObject: object)
            return (HTTPURLResponse(
                url: try XCTUnwrap(request.url), statusCode: 200,
                httpVersion: nil, headerFields: nil
            )!, data)
        }
        defer { URLProtocolStub.handler = nil; URLProtocolStub.requestNumber = 0 }
        let client = HAVREAPIClient(
            baseURL: URL(string: "https://owner.example")!,
            session: URLSession(configuration: configuration),
            tokenSource: FixedTokenSource()
        )
        let response = try await client.submitDeliveryAction(QueuedDeliveryAction(
            link: DeliveryLink(proposalID: proposal, deliveryAttemptID: attempt),
            action: .responded, responseText: "owner reply", idempotencyKey: "linked-action"
        ))
        XCTAssertEqual(response?.assistantEventID, assistantEvent)
        XCTAssertEqual(URLProtocolStub.requestNumber, 3)
    }

    func testSceneSignalEncodesExistingCoreContract() throws {
        let draft = SceneSignalDraft(
            sceneSessionID: UUID(), expectedRevision: 2,
            signalType: .needHelp, danger: .plausible, avoidance: .present,
            energy: .low, coercion: .absent,
            goalAlignment: .activeMeaningful, goalUrgency: .urgent
        )
        let object = try XCTUnwrap(
            JSONSerialization.jsonObject(with: JSONEncoder.havre.encode(draft)) as? [String: Any]
        )
        XCTAssertEqual(object["signalType"] as? String, "need_help")
        XCTAssertEqual(object["goalAlignment"] as? String, "active_meaningful")
    }

    func testReconcilerStopsInOrderAndKeepsBlockedEnvelope() async {
        let transport = RecordingTransport(failText: "two")
        let queue = OfflineQueue()
        let first = await queue.enqueue(.interaction(InteractionDraft(text: "one", privacyClass: .localOnly)))
        let second = await queue.enqueue(.interaction(InteractionDraft(text: "two", privacyClass: .localOnly)))
        _ = await queue.enqueue(.interaction(InteractionDraft(text: "three", privacyClass: .localOnly)))
        let report = await OfflineReconciler(transport: transport).reconcile(queue)
        XCTAssertEqual(report.acknowledged, [first.id])
        XCTAssertEqual(report.interactions.map(\.envelopeID), [first.id])
        XCTAssertEqual(report.blockedEnvelopeID, second.id)
        let remaining = await queue.pending().map(\.id)
        XCTAssertEqual(remaining.first, second.id)
    }
}

private struct FixedTokenSource: BearerTokenSource {
    func token() async throws -> String { "owner-token" }
}

private final class URLProtocolStub: URLProtocol, @unchecked Sendable {
    nonisolated(unsafe) static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?
    nonisolated(unsafe) static var requestNumber = 0
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        do {
            let (response, data) = try XCTUnwrap(Self.handler)(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch { client?.urlProtocol(self, didFailWithError: error) }
    }
    override func stopLoading() {}
}

private actor RecordingTransport: OfflineTransport {
    let failText: String
    init(failText: String) { self.failText = failText }
    func send(_ draft: InteractionDraft) async throws -> InteractionResponse {
        if draft.text == failText { throw HAVREAPIError.invalidResponse }
        return InteractionResponse(
            requestID: UUID(), userEventID: UUID(), assistantEventID: UUID(), content: "ok"
        )
    }
    func submitSceneSignal(_ draft: SceneSignalDraft) async throws {}
    func submitSceneTransition(_ draft: SceneTransitionDraft) async throws {}
    func submitDeliveryAction(_ action: QueuedDeliveryAction) async throws -> InteractionResponse? { nil }
}
