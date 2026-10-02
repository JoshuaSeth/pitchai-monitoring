import Foundation

internal struct SnapshotSource: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case error = "error"
        case lastSafeProbeAt = "last_safe_probe_at"
        case newestAccountProbeAt = "newest_account_probe_at"
        case stale = "stale"
        case staleAccountCount = "stale_account_count"
    }

    internal let stale: Bool
    internal let staleAccountCount: Int
    internal let newestAccountProbeAt: String?
    internal let lastSafeProbeAt: String?
    internal let error: String?
}
