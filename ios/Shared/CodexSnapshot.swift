import Foundation

internal struct CodexSnapshot: Codable, Equatable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case accounts = "accounts"
        case generatedAt = "generated_at"
        case refreshPolicy = "refresh_policy"
        case schemaVersion = "schema_version"
        case source = "source"
        case summary = "summary"
        case warnings = "warnings"
    }

    private static let freshnessIntervalSeconds: TimeInterval = 1_200

    internal let schemaVersion: Int
    internal let generatedAt: String
    internal let source: SnapshotSource
    internal let summary: SnapshotSummary
    internal let warnings: [CapacityWarning]
    internal let accounts: [CodexAccount]
    internal let refreshPolicy: RefreshPolicy

    internal var generatedDate: Date? {
        ServerDateParser.parse(generatedAt)
    }

    internal var isStale: Bool {
        if source.stale {
            return true
        }
        guard let generatedDate else {
            return true
        }
        return Date().timeIntervalSince(generatedDate) > Self.freshnessIntervalSeconds
    }

    internal var selectedAggregate: WindowAggregate? {
        switch summary.capacityBasis.key {
        case "five_hour":
            return summary.windowAggregates.fiveHour

        case "weekly":
            return summary.windowAggregates.weekly

        default:
            return nil
        }
    }

    internal var importantWarningCount: Int {
        warnings.filter { warning in
            warning.severity == "critical" || warning.severity == "warning"
        }.count
    }

    internal var requiresAttention: Bool {
        isStale || summary.usableNow == 0 || importantWarningCount > 0
    }
}
