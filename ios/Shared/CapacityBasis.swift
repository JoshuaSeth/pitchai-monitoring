import Foundation

internal struct CapacityBasis: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case eligibleAccounts = "eligible_accounts"
        case key = "key"
        case label = "label"
        case measurementStatus = "measurement_status"
        case reportingAccounts = "reporting_accounts"
    }

    internal let key: String?
    internal let label: String?
    internal let reportingAccounts: Int
    internal let eligibleAccounts: Int
    internal let measurementStatus: String?
}
