import Foundation

internal struct OpenCodeSubscriptionSet: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case accounts = "accounts"
        case error = "error"
        case generatedAt = "generated_at"
        case schemaVersion = "schema_version"
        case stale = "stale"
        case summary = "summary"
    }

    internal let schemaVersion: Int
    internal let generatedAt: String?
    internal let stale: Bool
    internal let error: String?
    internal let summary: OpenCodeSummary
    internal let accounts: [OpenCodeSubscription]

    internal var generatedDate: Date? {
        generatedAt.flatMap(ServerDateParser.parse)
    }
}
