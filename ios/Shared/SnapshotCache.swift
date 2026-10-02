import Foundation

internal enum SnapshotCacheError: LocalizedError {
    case appGroupUnavailable
    case encodingFailed
    #if DEBUG
        case diagnosticPayloadMissing
        case diagnosticPayloadInvalid
    #endif

    internal var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            return "The private shared snapshot container is unavailable."

        case .encodingFailed:
            return "The capacity snapshot could not be encoded."

        #if DEBUG
            case .diagnosticPayloadMissing:
                return "The diagnostic snapshot argument is missing its payload."

            case .diagnosticPayloadInvalid:
                return "The diagnostic snapshot payload is invalid."
        #endif
        }
    }
}

internal enum SnapshotCache {
    internal static let appGroup: String = "group.com.pitchai.codexstatus"
    internal static let snapshotKey: String = "codex-status.snapshot.v1"
    internal static let snapshotFileName: String = "codex-status-snapshot-v1.json"

    #if DEBUG
        internal static let diagnosticSnapshotArgument: String =
            "-CodexStatusDiagnosticSnapshotBase64"
    #endif

    internal static func sharedContainerURL() throws -> URL {
        guard
            let url: URL = FileManager.default.containerURL(
                forSecurityApplicationGroupIdentifier: appGroup
            )
        else {
            throw SnapshotCacheError.appGroupUnavailable
        }
        return url
    }

    internal static func load(from defaults: UserDefaults? = nil) -> CodexSnapshot? {
        if let defaults {
            guard let data: Data = defaults.data(forKey: snapshotKey) else {
                return nil
            }
            return decode(data)
        }
        guard let container: URL = containerURL() else {
            return nil
        }
        let destination: URL = container.appendingPathComponent(snapshotFileName)
        if FileManager.default.fileExists(atPath: destination.path) {
            guard let data: Data = fileContents(of: destination) else {
                return nil
            }
            return decode(data)
        }
        guard let legacyDefaults: UserDefaults = .init(suiteName: appGroup) else {
            return nil
        }
        return migrateLegacySnapshot(from: legacyDefaults, to: destination)
    }

    internal static func migrateLegacySnapshot(
        from defaults: UserDefaults,
        to destination: URL
    ) -> CodexSnapshot? {
        guard let data: Data = defaults.data(forKey: snapshotKey),
            let snapshot: CodexSnapshot = decode(data)
        else {
            return nil
        }
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

    internal static func save(_ snapshot: CodexSnapshot, to defaults: UserDefaults? = nil) throws {
        let data: Data = try encoded(snapshot)
        if let defaults {
            defaults.set(data, forKey: snapshotKey)
            return
        }
        let destination: URL = try sharedContainerURL().appendingPathComponent(snapshotFileName)
        try data.write(
            to: destination,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    internal static func encoded(_ snapshot: CodexSnapshot) throws -> Data {
        let encoder: JSONEncoder = .init()
        encoder.outputFormatting = [.sortedKeys]
        do {
            return try encoder.encode(snapshot)
        } catch {
            throw SnapshotCacheError.encodingFailed
        }
    }

    #if DEBUG
        internal static func diagnosticSnapshot(arguments: [String]) throws -> CodexSnapshot? {
            guard
                let argumentIndex: Array<String>.Index = arguments.firstIndex(
                    of: diagnosticSnapshotArgument
                )
            else {
                return nil
            }
            let payloadIndex: Array<String>.Index = arguments.index(after: argumentIndex)
            guard arguments.indices.contains(payloadIndex) else {
                throw SnapshotCacheError.diagnosticPayloadMissing
            }
            guard let data: Data = .init(base64Encoded: arguments[payloadIndex]),
                let snapshot: CodexSnapshot = decode(data)
            else {
                throw SnapshotCacheError.diagnosticPayloadInvalid
            }
            return snapshot
        }
    #endif

    private static func containerURL() -> URL? {
        do {
            return try sharedContainerURL()
        } catch {
            return nil
        }
    }

    private static func fileContents(of url: URL) -> Data? {
        do {
            return try Data(contentsOf: url)
        } catch {
            return nil
        }
    }

    private static func decode(_ data: Data) -> CodexSnapshot? {
        do {
            return try JSONDecoder().decode(CodexSnapshot.self, from: data)
        } catch {
            return nil
        }
    }
}
