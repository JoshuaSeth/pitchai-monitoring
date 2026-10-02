import Foundation

internal struct SnapshotSummary: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case capacityBasis = "capacity_basis"
        case configuredAccounts = "configured_accounts"
        case enabledAccounts = "enabled_accounts"
        case nextUsefulCapacityAt = "next_useful_capacity_at"
        case nextUsefulCapacityLabel = "next_useful_capacity_label"
        case statusCounts = "status_counts"
        case usableNow = "usable_now"
        case windowAggregates = "window_aggregates"
    }

    internal let configuredAccounts: Int
    internal let enabledAccounts: Int
    internal let usableNow: Int
    internal let statusCounts: StatusCounts
    internal let capacityBasis: CapacityBasis
    internal let windowAggregates: WindowAggregates
    internal let nextUsefulCapacityAt: String?
    internal let nextUsefulCapacityLabel: String?
}
