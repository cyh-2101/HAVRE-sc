import Foundation
import HAVREMobileCore

private struct BenchmarkTransport: OfflineTransport {
    func send(_ draft: InteractionDraft) async throws -> InteractionResponse {
        InteractionResponse(
            requestID: UUID(), userEventID: UUID(), assistantEventID: UUID(), content: "ok"
        )
    }
    func submitSceneSignal(_ draft: SceneSignalDraft) async throws {}
    func submitSceneTransition(_ draft: SceneTransitionDraft) async throws {}
    func submitDeliveryAction(_ action: QueuedDeliveryAction) async throws -> InteractionResponse? { nil }
}

@main
struct HAVREMobileBenchmarks {
    static func main() async throws {
        let count = 5_000
        let queue = OfflineQueue()
        let enqueueStart = ContinuousClock.now
        for index in 0..<count {
            await queue.enqueue(.interaction(InteractionDraft(
                text: "synthetic-portable-load-\(index)", privacyClass: .localOnly,
                memoryEligible: false, idempotencyKey: "portable-load-\(index)"
            )))
        }
        let enqueueDuration = enqueueStart.duration(to: .now)
        let encodeStart = ContinuousClock.now
        let bytes = try await queue.encoded()
        let restored = try OfflineQueue.decode(bytes)
        let encodeDuration = encodeStart.duration(to: .now)
        let reconcileStart = ContinuousClock.now
        let report = await OfflineReconciler(transport: BenchmarkTransport()).reconcile(restored)
        let reconcileDuration = reconcileStart.duration(to: .now)
        let remaining = await restored.pending().count
        let result: [String: Any] = [
            "schema_version": 1,
            "fixture": "synthetic-local-only-no-network",
            "envelopes": count,
            "encoded_bytes": bytes.count,
            "acknowledged": report.acknowledged.count,
            "remaining": remaining,
            "blocked": report.blockedEnvelopeID != nil,
            "enqueue_ms": milliseconds(enqueueDuration),
            "encode_decode_ms": milliseconds(encodeDuration),
            "reconcile_ms": milliseconds(reconcileDuration),
        ]
        let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
        print(String(decoding: data, as: UTF8.self))
    }

    private static func milliseconds(_ duration: Duration) -> Double {
        let parts = duration.components
        return Double(parts.seconds) * 1_000 + Double(parts.attoseconds) / 1e15
    }
}
