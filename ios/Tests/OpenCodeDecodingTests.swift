import Foundation
import Testing

@testable import CodexStatus

internal struct OpenCodeDecodingTests {
    @Test
    internal func openCodeSubscriptionsDecodeFromTheServerContract() throws {
        let json: String = """
            {
                "schema_version": 1, "generated_at": "2026-10-06T08:16:59Z", "stale": false,
                "error": null,
                "summary": {
                    "subscriptions": 1, "ready": 0, "limited": 1,
                    "next_available_at": "2026-10-22T16:59:26Z"
                },
                "accounts": [{
                    "label": "info@pitchai.net", "position": 1, "status": "limited",
                    "limited_by": ["monthly"], "available_at": "2026-10-22T16:59:26Z",
                    "bridge_last_status": 429.0, "bridge_cooldown_until": null, "error": null,
                    "windows": {
                        "monthly": {
                            "reported": true, "used_percent": 100.0, "remaining_percent": 0.0,
                            "reset_at": "2026-10-22T16:59:26Z", "reset_in_seconds": 1406547,
                            "window_seconds": null, "status": "rate-limited"
                        }
                    }
                }]
            }
            """
        let decoded: OpenCodeSubscriptionSet = try JSONDecoder().decode(
            OpenCodeSubscriptionSet.self,
            from: Data(json.utf8)
        )
        let first: OpenCodeSubscription = try #require(decoded.accounts.first)

        #expect(first.status == "limited")
        #expect(first.windows.monthly?.remainingPercent == 0)
        #expect(first.windows.rolling == nil)
        #expect(first.bridgeLastStatus == 429)
        #expect(decoded.summary.nextAvailableAt == "2026-10-22T16:59:26Z")
    }

    @Test
    internal func fixtureSnapshotCarriesTheOpenCodeList() {
        let subscriptions: OpenCodeSubscriptionSet? = CodexSnapshot.fixture.openCodeSubscriptions

        #expect(subscriptions?.accounts.first?.label == "info@pitchai.net")
        #expect(subscriptions?.summary.ready == 0)
    }
}
