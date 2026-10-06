import Foundation

internal struct OpenCodeSummary: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case limited = "limited"
        case nextAvailableAt = "next_available_at"
        case ready = "ready"
        case subscriptions = "subscriptions"
    }

    internal let subscriptions: Int
    internal let ready: Int
    internal let limited: Int
    internal let nextAvailableAt: String?
}
