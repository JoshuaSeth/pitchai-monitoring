import Foundation

internal struct RefreshPolicy: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case manualMinIntervalSeconds = "manual_min_interval_seconds"
        case recommendedBackgroundIntervalSeconds = "recommended_background_interval_seconds"
    }

    internal let manualMinIntervalSeconds: Int
    internal let recommendedBackgroundIntervalSeconds: Int
}
