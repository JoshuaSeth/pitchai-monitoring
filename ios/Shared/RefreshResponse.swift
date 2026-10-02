import Foundation

internal struct RefreshResponse: Codable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case probeStarted = "probe_started"
        case reason = "reason"
        case retryAfterSeconds = "retry_after_seconds"
        case schemaVersion = "schema_version"
        case snapshot = "snapshot"
    }

    internal let schemaVersion: Int
    internal let probeStarted: Bool
    internal let reason: String?
    internal let retryAfterSeconds: Int?
    internal let snapshot: CodexSnapshot
}
