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

    static func sharedDefaults() throws -> UserDefaults {
        guard let defaults = UserDefaults(suiteName: appGroup) else {
            throw SnapshotCacheError.appGroupUnavailable
        }
        return defaults
    }

    static func load(from defaults: UserDefaults? = nil) -> CodexSnapshot? {
        let resolved: UserDefaults
        if let defaults {
            resolved = defaults
        } else {
            guard let shared = try? sharedDefaults() else { return nil }
            resolved = shared
        }
        guard let data = resolved.data(forKey: snapshotKey) else { return nil }
        return try? JSONDecoder().decode(CodexSnapshot.self, from: data)
    }

    static func save(_ snapshot: CodexSnapshot, to defaults: UserDefaults? = nil) throws {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        guard let data = try? encoder.encode(snapshot) else {
            throw SnapshotCacheError.encodingFailed
        }
        let resolved: UserDefaults
        if let defaults {
            resolved = defaults
        } else {
            resolved = try sharedDefaults()
        }
        resolved.set(data, forKey: snapshotKey)
    }

    static func encoded(_ snapshot: CodexSnapshot) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        return try encoder.encode(snapshot)
    }
}
