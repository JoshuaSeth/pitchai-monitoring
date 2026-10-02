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
