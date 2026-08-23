import XCTest
@testable import CodexStatus

final class CodexStatusTests: XCTestCase {
    func testNativeSnapshotDecodesUnknownWindowsWithoutInventingCapacity() throws {
        let json = #"""
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
        """#.data(using: .utf8)!

        let snapshot = try JSONDecoder().decode(CodexSnapshot.self, from: json)

        XCTAssertTrue(snapshot.isStale)
        XCTAssertNil(snapshot.selectedAggregate)
        XCTAssertNil(snapshot.accounts[0].fiveHour.remainingPercent)
        XCTAssertFalse(snapshot.accounts[0].fiveHour.reported)
        XCTAssertEqual(snapshot.warnings[0].accountLabel, "Primary")
        XCTAssertEqual(snapshot.importantWarningCount, 1)
        XCTAssertTrue(snapshot.requiresAttention)
    }

    func testCanonicalAssertionDataMatchesServerContract() throws {
        let data = try SecureCapacityClient.canonicalClientData(
            purpose: "capacity",
            challengeID: "11111111-2222-3333-4444-555555555555",
            challenge: "Y2hhbGxlbmdl",
            keyID: "a2V5"
        )

        XCTAssertEqual(
            String(decoding: data, as: UTF8.self),
            "pitchai-codex-status-v1\ncapacity\n11111111-2222-3333-4444-555555555555\nY2hhbGxlbmdl\na2V5"
        )
    }

    func testPrivateSnapshotCacheRoundTripsOnlyTheNativeModel() throws {
        let suite = "CodexStatusTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        let fixture = CodexSnapshot.fixture
        try SnapshotCache.save(fixture, to: defaults)
        let loaded = try XCTUnwrap(SnapshotCache.load(from: defaults))

        XCTAssertEqual(loaded, fixture)
        let encoded = try XCTUnwrap(defaults.data(forKey: SnapshotCache.snapshotKey))
        let text = String(decoding: encoded, as: UTF8.self)
        XCTAssertFalse(text.contains("access_token"))
        XCTAssertFalse(text.contains("refresh_token"))
        XCTAssertFalse(text.contains("admin_token"))
    }

    func testPrivateSnapshotCacheMigratesLegacyDefaultsIntoProtectedFile() throws {
        let suite = "CodexStatusTests.\(UUID().uuidString)"
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("CodexStatusTests.\(UUID().uuidString)", isDirectory: true)
        let destination = directory.appendingPathComponent(SnapshotCache.snapshotFileName)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer {
            defaults.removePersistentDomain(forName: suite)
            try? FileManager.default.removeItem(at: directory)
        }

        let fixture = CodexSnapshot.fixture
        try SnapshotCache.save(fixture, to: defaults)

        let migrated = try XCTUnwrap(
            SnapshotCache.migrateLegacySnapshot(from: defaults, to: destination)
        )

        XCTAssertEqual(migrated, fixture)
        XCTAssertNil(defaults.data(forKey: SnapshotCache.snapshotKey))
        let protectedData = try Data(contentsOf: destination)
        XCTAssertEqual(try JSONDecoder().decode(CodexSnapshot.self, from: protectedData), fixture)
    }

#if DEBUG
    func testDiagnosticSnapshotArgumentDecodesNativeSnapshot() throws {
        let fixture = CodexSnapshot.fixture
        let encoded = try SnapshotCache.encoded(fixture)
        let decoded = try SnapshotCache.diagnosticSnapshot(
            arguments: [
                "CodexStatusWatch",
                SnapshotCache.diagnosticSnapshotArgument,
                encoded.base64EncodedString(),
            ]
        )

        XCTAssertEqual(decoded, fixture)
    }

    func testDiagnosticSnapshotArgumentFailsLoudlyWhenPayloadIsMissing() {
        XCTAssertThrowsError(
            try SnapshotCache.diagnosticSnapshot(
                arguments: ["CodexStatusWatch", SnapshotCache.diagnosticSnapshotArgument]
            )
        ) { error in
            XCTAssertEqual(
                error.localizedDescription,
                SnapshotCacheError.diagnosticPayloadMissing.localizedDescription
            )
        }
    }
#endif
}
