import Foundation
import Testing

@testable import CodexStatus

internal struct PhysicalLiveTests {
    private static func physicalFailure(stage: String, error: Error) -> Comment {
        let classification: String
        if let clientError = error as? CapacityClientError {
            classification = clientClassification(clientError)
        } else if let cacheError = error as? SnapshotCacheError {
            classification = cacheClassification(cacheError)
        } else {
            let cocoaError: NSError = error as NSError
            classification = "\(cocoaError.domain)_\(cocoaError.code)"
        }
        return Comment(rawValue: "physical_live_stage=\(stage) classification=\(classification)")
    }

    private static func clientClassification(_ error: CapacityClientError) -> String {
        switch error {
        case .appAttestUnavailable:
            return "app_attest_unavailable"

        case .invalidServerResponse:
            return "invalid_server_response"

        case .serverRejected(let rejection):
            return "server_rejected_\(rejection.status)"

        case .challengeInvalid:
            return "challenge_invalid"
        }
    }

    private static func cacheClassification(_ error: SnapshotCacheError) -> String {
        switch error {
        case .appGroupUnavailable:
            return "app_group_unavailable"

        case .encodingFailed:
            return "encoding_failed"

        #if DEBUG
            case .diagnosticPayloadMissing:
                return "diagnostic_payload_missing"

            case .diagnosticPayloadInvalid:
                return "diagnostic_payload_invalid"
        #endif
        }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["CODEX_STATUS_PHYSICAL_LIVE"] == "1"))
    internal func testPhysicalLiveSnapshotPersistsProtectedAppGroupCache() async throws {
        let snapshot: CodexSnapshot
        do {
            snapshot = try await SecureCapacityClient.live.fetchCapacity()
        } catch {
            Issue.record(Self.physicalFailure(stage: "fetch", error: error))
            return
        }

        #expect(snapshot.schemaVersion == 1)
        #expect(snapshot.summary.configuredAccounts > 0)
        #expect(snapshot.summary.enabledAccounts >= snapshot.summary.usableNow)

        do {
            try SnapshotCache.save(snapshot)
        } catch {
            Issue.record(Self.physicalFailure(stage: "cache_write", error: error))
            return
        }

        let loaded: CodexSnapshot? = SnapshotCache.load()
        guard let loaded else {
            Issue.record("physical_live_stage=cache_reload classification=missing_snapshot")
            return
        }
        #expect(loaded == snapshot)

        let encoded: Data = try SnapshotCache.encoded(loaded)
        let text: String = .init(decoding: encoded, as: UTF8.self)
        for forbiddenKey in ["access_token", "refresh_token", "admin_token", "key_id"] {
            #expect(!text.contains(forbiddenKey))
        }
    }

    @Test(.enabled(if: ProcessInfo.processInfo.environment["CODEX_STATUS_PHYSICAL_LIVE"] == "1"))
    internal func testPhysicalAppLaunchSnapshotIsAvailableToExtensions() throws {
        let snapshot: CodexSnapshot? = SnapshotCache.load()
        guard let snapshot else {
            Issue.record("physical_live_stage=extension_cache classification=missing_snapshot")
            return
        }

        #expect(snapshot.schemaVersion == 1)
        #expect(snapshot.summary.configuredAccounts > 0)
        #expect(snapshot.summary.enabledAccounts >= snapshot.summary.usableNow)
    }
}
