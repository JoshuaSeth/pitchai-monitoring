import Foundation

enum SnapshotCacheError: LocalizedError {
    case appGroupUnavailable
    case encodingFailed
#if DEBUG
    case diagnosticPayloadMissing
    case diagnosticPayloadInvalid
#endif

    var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            "The private shared snapshot container is unavailable."
        case .encodingFailed:
            "The capacity snapshot could not be encoded."
#if DEBUG
        case .diagnosticPayloadMissing:
            "The diagnostic snapshot argument is missing its payload."
        case .diagnosticPayloadInvalid:
            "The diagnostic snapshot payload is invalid."
#endif
        }
    }
}

enum SnapshotCache {
    static let appGroup = "group.com.pitchai.codexstatus"
    static let snapshotKey = "codex-status.snapshot.v1"
    static let snapshotFileName = "codex-status-snapshot-v1.json"
#if DEBUG
    static let diagnosticSnapshotArgument = "-CodexStatusDiagnosticSnapshotBase64"
#endif

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

#if DEBUG
    static func diagnosticSnapshot(arguments: [String]) throws -> CodexSnapshot? {
        guard let argumentIndex = arguments.firstIndex(of: diagnosticSnapshotArgument) else {
            return nil
        }
        let payloadIndex = arguments.index(after: argumentIndex)
        guard arguments.indices.contains(payloadIndex) else {
            throw SnapshotCacheError.diagnosticPayloadMissing
        }
        guard let data = Data(base64Encoded: arguments[payloadIndex]),
              let snapshot = try? JSONDecoder().decode(CodexSnapshot.self, from: data)
        else {
            throw SnapshotCacheError.diagnosticPayloadInvalid
        }
        return snapshot
    }
#endif
}
