import Foundation

internal struct StatusCounts: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case authInvalid = "auth_invalid"
        case available = "available"
        case disabled = "disabled"
        case fiveHourLimited = "five_hour_limited"
        case unknown = "unknown"
        case weeklyLimited = "weekly_limited"
    }

    internal let available: Int
    internal let fiveHourLimited: Int
    internal let weeklyLimited: Int
    internal let authInvalid: Int
    internal let disabled: Int
    internal let unknown: Int
}
