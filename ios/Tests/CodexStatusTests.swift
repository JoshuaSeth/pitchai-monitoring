import Foundation
import Testing

@testable import CodexStatus

internal struct CodexStatusTests {
    @Test
    internal func canonicalAssertionDataMatchesServerContract() throws {
        let data: Data = try SecureCapacityClient.canonicalClientData(
            purpose: "capacity",
            challengeID: "11111111-2222-3333-4444-555555555555",
            challenge: "Y2hhbGxlbmdl",
            keyID: "a2V5"
        )
        let expected: String =
            "pitchai-codex-status-v1\ncapacity\n11111111-2222-3333-4444-555555555555\n"
            + "Y2hhbGxlbmdl\na2V5"

        #expect(String(decoding: data, as: UTF8.self) == expected)
    }

    @Test
    internal func privateSnapshotCacheRoundTripsOnlyTheNativeModel() throws {
        let suite: String = "CodexStatusTests.\(UUID().uuidString)"
        let defaults: UserDefaults = try #require(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }

        let fixture: CodexSnapshot = .fixture
        try SnapshotCache.save(fixture, to: defaults)
        let loaded: CodexSnapshot = try #require(SnapshotCache.load(from: defaults))

        #expect(loaded == fixture)
        let encoded: Data = try #require(defaults.data(forKey: SnapshotCache.snapshotKey))
        let text: String = .init(decoding: encoded, as: UTF8.self)
        #expect(!text.contains("access_token"))
        #expect(!text.contains("refresh_token"))
        #expect(!text.contains("admin_token"))
    }

    @Test
    internal func privateSnapshotCacheMigratesLegacyDefaultsIntoProtectedFile() throws {
        let suite: String = "CodexStatusTests.\(UUID().uuidString)"
        let defaults: UserDefaults = try #require(UserDefaults(suiteName: suite))
        let directory: URL = FileManager.default.temporaryDirectory
            .appendingPathComponent("CodexStatusTests.\(UUID().uuidString)", isDirectory: true)
        let destination: URL = directory.appendingPathComponent(SnapshotCache.snapshotFileName)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        defer {
            defaults.removePersistentDomain(forName: suite)
            do {
                try FileManager.default.removeItem(at: directory)
            } catch {
                // The per-test temporary directory is disposable; cleanup is best effort.
            }
        }

        let fixture: CodexSnapshot = .fixture
        try SnapshotCache.save(fixture, to: defaults)

        let migrated: CodexSnapshot = try #require(
            SnapshotCache.migrateLegacySnapshot(from: defaults, to: destination)
        )

        #expect(migrated == fixture)
        #expect(defaults.data(forKey: SnapshotCache.snapshotKey) == nil)
        let protectedData: Data = try .init(contentsOf: destination)
        #expect(try JSONDecoder().decode(CodexSnapshot.self, from: protectedData) == fixture)
    }

    @Test
    internal func burnFactorsDecodeFromTheServerContract() throws {
        let json: String = """
            {"schema_version": 1, "generated_at": "2026-10-05T16:00:00Z", "pools": [{
                "key": "deepseek", "label": "DeepSeek", "unit": "usd", "balance_usd": 0.0,
                "results": [{
                    "rolling": "24h", "horizon": "6d", "factor": null, "status": "short",
                    "lower_bound": false, "runway_hours": null, "burn_per_hour": 1.14,
                    "demand": 164.63, "available": 0.0, "margin": -164.63, "blocked_until": null
                }]
            }]}
            """
        let decoded: BurnFactorSet = try JSONDecoder().decode(
            BurnFactorSet.self,
            from: Data(json.utf8)
        )
        let pool: BurnFactorPool = try #require(decoded.pool("deepseek"))

        #expect(pool.isMoney)
        #expect(pool.shortTerm == nil)
        #expect(BurnFactorFormatting.factor(pool.longTerm) == "∞")
        #expect(BurnFactorFormatting.gaugeValue(pool.longTerm) == BurnFactorFormatting.gaugeMaximum)
    }

    @Test
    internal func snapshotsFromOlderServersDecodeWithoutBurnFactors() throws {
        var legacy: CodexSnapshot = .fixture
        legacy.burnFactors = nil
        let data: Data = try JSONEncoder().encode(legacy)
        let text: String = .init(decoding: data, as: UTF8.self)
        let decoded: CodexSnapshot = try JSONDecoder().decode(CodexSnapshot.self, from: data)

        #expect(!text.contains("burn_factors"))
        #expect(decoded.burnFactors == nil)
        #expect(CodexSnapshot.fixture.burnFactors?.pool("openai")?.label == "Codex")
    }

    #if DEBUG
        @Test
        internal func diagnosticSnapshotArgumentDecodesNativeSnapshot() throws {
            let fixture: CodexSnapshot = .fixture
            let encoded: Data = try SnapshotCache.encoded(fixture)
            let base64: String = encoded.base64EncodedString()
            let action: String = "CodexStatusWatch"
            let arguments: [String] = [action, SnapshotCache.diagnosticSnapshotArgument, base64]

            let candidate: CodexSnapshot? = try SnapshotCache.diagnosticSnapshot(
                arguments: arguments
            )
            let decoded: CodexSnapshot = try #require(candidate)

            #expect(decoded == fixture)
        }

        @Test
        internal func diagnosticSnapshotArgumentFailsLoudlyWhenPayloadIsMissing() throws {
            let action: String = "CodexStatusWatch"
            let arguments: [String] = [action, SnapshotCache.diagnosticSnapshotArgument]

            do {
                _ = try SnapshotCache.diagnosticSnapshot(arguments: arguments)
                Issue.record("Expected the diagnostic snapshot payload to be reported as missing.")
            } catch {
                let expected: String = SnapshotCacheError.diagnosticPayloadMissing
                    .localizedDescription
                #expect(error.localizedDescription == expected)
            }
        }
    #endif
}
