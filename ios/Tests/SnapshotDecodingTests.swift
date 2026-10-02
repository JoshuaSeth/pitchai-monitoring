import Foundation
import Testing

@testable import CodexStatus

internal struct SnapshotDecodingTests {
    private static let unknownWindowPayload: String = #"""
        {
            "schema_version": 1,
            "generated_at": "2026-08-23T12:00:00Z",
            "source": {
                "stale": true,
                "stale_account_count": 1,
                "newest_account_probe_at": null,
                "last_safe_probe_at": null,
                "error": "TimeoutError"
            },
            "summary": {
                "configured_accounts": 1,
                "enabled_accounts": 1,
                "usable_now": 0,
                "status_counts": {
                    "available": 0,
                    "five_hour_limited": 0,
                    "weekly_limited": 0,
                    "auth_invalid": 0,
                    "disabled": 0,
                    "unknown": 1
                },
                "capacity_basis": {
                    "key": null,
                    "label": null,
                    "reporting_accounts": 0,
                    "eligible_accounts": 0,
                    "measurement_status": "unavailable"
                },
                "window_aggregates": {
                    "five_hour": {
                        "measurement_status": "unavailable",
                        "reporting_accounts": 0,
                        "unknown_accounts": 1,
                        "remaining_points": null,
                        "maximum_known_points": null,
                        "remaining_percent": null
                    },
                    "weekly": {
                        "measurement_status": "unavailable",
                        "reporting_accounts": 0,
                        "unknown_accounts": 1,
                        "remaining_points": null,
                        "maximum_known_points": null,
                        "remaining_percent": null
                    }
                },
                "next_useful_capacity_at": null,
                "next_useful_capacity_label": null
            },
            "warnings": [
                {
                    "severity": "warning",
                    "code": "unknown",
                    "account_label": "Primary",
                    "message": "Usage state unavailable"
                }
            ],
            "accounts": [
                {
                    "label": "Primary",
                    "enabled": true,
                    "routing_preferred": false,
                    "plan_type": null,
                    "status": "unknown",
                    "status_reason": "Usage state unavailable",
                    "auth_valid": null,
                    "selectable_now": false,
                    "safety_floor_active": false,
                    "five_hour": {
                        "reported": false,
                        "used_percent": null,
                        "remaining_percent": null,
                        "reset_at": null,
                        "reset_in_seconds": null,
                        "window_seconds": null
                    },
                    "weekly": {
                        "reported": false,
                        "used_percent": null,
                        "remaining_percent": null,
                        "reset_at": null,
                        "reset_in_seconds": null,
                        "window_seconds": null
                    },
                    "last_probe_at": null,
                    "stale": true,
                    "stale_seconds": null,
                    "probe_error": "TimeoutError"
                }
            ],
            "refresh_policy": {
                "manual_min_interval_seconds": 60,
                "recommended_background_interval_seconds": 900
            }
        }
        """#

    @Test
    internal func decodesUnknownWindowsWithoutInventingCapacity() throws {
        let payload: Data = try #require(Self.unknownWindowPayload.data(using: .utf8))
        let snapshot: CodexSnapshot = try JSONDecoder().decode(CodexSnapshot.self, from: payload)

        #expect(snapshot.isStale)
        #expect(snapshot.selectedAggregate == nil)
        #expect(snapshot.accounts[0].fiveHour.remainingPercent == nil)
        #expect(!snapshot.accounts[0].fiveHour.reported)
        #expect(snapshot.warnings[0].accountLabel == "Primary")
        #expect(snapshot.importantWarningCount == 1)
        #expect(snapshot.requiresAttention)
    }
}
