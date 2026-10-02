import Foundation

internal struct WindowAggregate: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case maximumKnownPoints = "maximum_known_points"
        case measurementStatus = "measurement_status"
        case remainingPercent = "remaining_percent"
        case remainingPoints = "remaining_points"
        case reportingAccounts = "reporting_accounts"
        case unknownAccounts = "unknown_accounts"
    }

    internal let measurementStatus: String?
    internal let reportingAccounts: Int?
    internal let unknownAccounts: Int?
    internal let remainingPoints: Double?
    internal let maximumKnownPoints: Double?
    internal let remainingPercent: Double?
}
