import Foundation

internal struct UsageWindow: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case remainingPercent = "remaining_percent"
        case reported = "reported"
        case resetAt = "reset_at"
        case resetInSeconds = "reset_in_seconds"
        case usedPercent = "used_percent"
        case windowSeconds = "window_seconds"
    }

    internal let reported: Bool
    internal let usedPercent: Double?
    internal let remainingPercent: Double?
    internal let resetAt: String?
    internal let resetInSeconds: Int?
    internal let windowSeconds: Int?

    internal var resetDate: Date? {
        resetAt.flatMap(ServerDateParser.parse)
    }
}
