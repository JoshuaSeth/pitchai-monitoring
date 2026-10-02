import Foundation

internal struct WindowAggregates: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case fiveHour = "five_hour"
        case weekly = "weekly"
    }

    internal let fiveHour: WindowAggregate
    internal let weekly: WindowAggregate
}
