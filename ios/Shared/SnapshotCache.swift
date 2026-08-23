import Foundation

enum SnapshotCacheError: LocalizedError {
    case appGroupUnavailable
    case encodingFailed

    var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            "The private shared snapshot container is unavailable."
        case .encodingFailed:
            "The capacity snapshot could not be encoded."
        }
    }
}

enum SnapshotCache {
    static let appGroup = "group.com.pitchai.codexstatus"
    static let snapshotKey = "codex-status.snapshot.v1"
    static let snapshotFileName = "codex-status-snapshot-v1.json"

    static func sharedContainerURL() throws -> URL {
        guard let url = FileManager.default.containerURL(
            forSecurityApplicationGroupIdentifier: appGroup
        ) else {
            throw SnapshotCacheError.appGroupUnavailable
        }
        return url
    }

    static func load(from defaults: UserDefaults? = nil) -> CodexSnapshot? {
        if let defaults {
            guard let data = defaults.data(forKey: snapshotKey) else { return nil }
            return try? JSONDecoder().decode(CodexSnapshot.self, from: data)
        }
        guard let container = try? sharedContainerURL() else { return nil }
        let destination = container.appendingPathComponent(snapshotFileName)
        if FileManager.default.fileExists(atPath: destination.path) {
            guard let data = try? Data(contentsOf: destination) else { return nil }
            return try? JSONDecoder().decode(CodexSnapshot.self, from: data)
        }
        guard let legacyDefaults = UserDefaults(suiteName: appGroup) else { return nil }
        return migrateLegacySnapshot(from: legacyDefaults, to: destination)
    }

    static func migrateLegacySnapshot(
        from defaults: UserDefaults,
        to destination: URL
    ) -> CodexSnapshot? {
        guard let data = defaults.data(forKey: snapshotKey),
              let snapshot = try? JSONDecoder().decode(CodexSnapshot.self, from: data)
        else { return nil }
        do {
            try data.write(
                to: destination,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            defaults.removeObject(forKey: snapshotKey)
            return snapshot
        } catch {
            return nil
        }
    }

    static func save(_ snapshot: CodexSnapshot, to defaults: UserDefaults? = nil) throws {
        let data = try encoded(snapshot)
        if let defaults {
            defaults.set(data, forKey: snapshotKey)
            return
        }
        let destination = try sharedContainerURL().appendingPathComponent(snapshotFileName)
        try data.write(
            to: destination,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    static func encoded(_ snapshot: CodexSnapshot) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        do {
            return try encoder.encode(snapshot)
        } catch {
            throw SnapshotCacheError.encodingFailed
        }
    }
}
