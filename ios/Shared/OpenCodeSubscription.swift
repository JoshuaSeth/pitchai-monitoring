import Foundation

internal struct OpenCodeSubscription: Codable, Equatable, Identifiable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case availableAt = "available_at"
        case bridgeCooldownUntil = "bridge_cooldown_until"
        case bridgeLastStatus = "bridge_last_status"
        case error = "error"
        case label = "label"
        case limitedBy = "limited_by"
        case position = "position"
        case status = "status"
        case windows = "windows"
    }

    internal let label: String
    internal let position: Int
    internal let status: String
    internal let limitedBy: [String]
    internal let availableAt: String?
    internal let windows: OpenCodeWindows
    internal let bridgeLastStatus: Double?
    internal let bridgeCooldownUntil: String?
    internal let error: String?

    internal var id: String {
        label
    }
}
