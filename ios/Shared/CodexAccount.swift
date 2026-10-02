import Foundation

internal struct CodexAccount: Codable, Equatable, Identifiable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case enabled = "enabled"
        case fiveHour = "five_hour"
        case label = "label"
        case lastProbeAt = "last_probe_at"
        case planType = "plan_type"
        case probeError = "probe_error"
        case routingPreferred = "routing_preferred"
        case safetyFloorActive = "safety_floor_active"
        case selectableNow = "selectable_now"
        case stale = "stale"
        case staleSeconds = "stale_seconds"
        case status = "status"
        case statusReason = "status_reason"
        case weekly = "weekly"
    }

    internal let label: String
    internal let enabled: Bool
    internal let routingPreferred: Bool
    internal let planType: String?
    internal let status: String
    internal let statusReason: String
    internal let selectableNow: Bool
    internal let safetyFloorActive: Bool
    internal let fiveHour: UsageWindow
    internal let weekly: UsageWindow
    internal let lastProbeAt: String?
    internal let stale: Bool
    internal let staleSeconds: Int?
    internal let probeError: String?

    internal var id: String {
        label
    }
}
