import Foundation

struct CodexSnapshot: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let generatedAt: String
    let source: SnapshotSource
    let summary: SnapshotSummary
    let warnings: [CapacityWarning]
    let accounts: [CodexAccount]
    let refreshPolicy: RefreshPolicy

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case generatedAt = "generated_at"
        case source
        case summary
        case warnings
        case accounts
        case refreshPolicy = "refresh_policy"
    }

    var generatedDate: Date? {
        ServerDateParser.parse(generatedAt)
    }

    var isStale: Bool {
        if source.stale { return true }
        guard let generatedDate else { return true }
        return Date().timeIntervalSince(generatedDate) > 20 * 60
    }

    var selectedAggregate: WindowAggregate? {
        switch summary.capacityBasis.key {
        case "five_hour": summary.windowAggregates.fiveHour
        case "weekly": summary.windowAggregates.weekly
        default: nil
        }
    }

    var importantWarningCount: Int {
        warnings.filter { warning in
            warning.severity == "critical" || warning.severity == "warning"
        }.count
    }

    var requiresAttention: Bool {
        isStale || summary.usableNow == 0 || importantWarningCount > 0
    }

    static var fixture: CodexSnapshot {
        let now = Date()
        return CodexSnapshot(
            schemaVersion: 1,
            generatedAt: ServerDateParser.string(now),
            source: SnapshotSource(
                stale: false,
                staleAccountCount: 0,
                newestAccountProbeAt: ServerDateParser.string(now.addingTimeInterval(-32)),
                lastSafeProbeAt: ServerDateParser.string(now.addingTimeInterval(-32)),
                error: nil
            ),
            summary: SnapshotSummary(
                configuredAccounts: 4,
                enabledAccounts: 4,
                usableNow: 2,
                statusCounts: StatusCounts(
                    available: 2,
                    fiveHourLimited: 1,
                    weeklyLimited: 0,
                    authInvalid: 1,
                    disabled: 0,
                    unknown: 0
                ),
                capacityBasis: CapacityBasis(
                    key: "five_hour",
                    label: "Five-hour",
                    reportingAccounts: 4,
                    eligibleAccounts: 4,
                    measurementStatus: "complete"
                ),
                windowAggregates: WindowAggregates(
                    fiveHour: WindowAggregate(
                        measurementStatus: "complete",
                        reportingAccounts: 4,
                        unknownAccounts: 0,
                        remainingPoints: 213,
                        maximumKnownPoints: 400,
                        remainingPercent: 53.3
                    ),
                    weekly: WindowAggregate(
                        measurementStatus: "complete",
                        reportingAccounts: 4,
                        unknownAccounts: 0,
                        remainingPoints: 268,
                        maximumKnownPoints: 400,
                        remainingPercent: 67
                    )
                ),
                nextUsefulCapacityAt: ServerDateParser.string(now.addingTimeInterval(42 * 60)),
                nextUsefulCapacityLabel: "Team reserve"
            ),
            warnings: [
                CapacityWarning(
                    severity: "critical",
                    code: "auth_invalid",
                    accountLabel: "Research",
                    message: "Account needs login or token refresh"
                )
            ],
            accounts: [
                CodexAccount.fixture(
                    label: "Primary",
                    status: "available",
                    reason: "Selectable now",
                    preferred: true,
                    fiveRemaining: 84,
                    fiveReset: now.addingTimeInterval(4_180),
                    weeklyRemaining: 72,
                    weeklyReset: now.addingTimeInterval(3 * 86_400)
                ),
                CodexAccount.fixture(
                    label: "Team reserve",
                    status: "five_hour_limited",
                    reason: "Held at broker five-hour safety floor",
                    preferred: false,
                    fiveRemaining: 10,
                    fiveReset: now.addingTimeInterval(42 * 60),
                    weeklyRemaining: 64,
                    weeklyReset: now.addingTimeInterval(4 * 86_400)
                ),
                CodexAccount.fixture(
                    label: "Operations",
                    status: "available",
                    reason: "Selectable now",
                    preferred: false,
                    fiveRemaining: 59,
                    fiveReset: now.addingTimeInterval(2 * 3_600),
                    weeklyRemaining: 81,
                    weeklyReset: now.addingTimeInterval(5 * 86_400)
                ),
                CodexAccount.fixture(
                    label: "Research",
                    status: "auth_invalid",
                    reason: "Login or token refresh required",
                    preferred: false,
                    fiveRemaining: 60,
                    fiveReset: now.addingTimeInterval(3 * 3_600),
                    weeklyRemaining: 51,
                    weeklyReset: now.addingTimeInterval(2 * 86_400)
                )
            ],
            refreshPolicy: RefreshPolicy(
                manualMinIntervalSeconds: 60,
                recommendedBackgroundIntervalSeconds: 900
            )
        )
    }
}

struct SnapshotSource: Codable, Equatable, Sendable {
    let stale: Bool
    let staleAccountCount: Int
    let newestAccountProbeAt: String?
    let lastSafeProbeAt: String?
    let error: String?

    enum CodingKeys: String, CodingKey {
        case stale
        case staleAccountCount = "stale_account_count"
        case newestAccountProbeAt = "newest_account_probe_at"
        case lastSafeProbeAt = "last_safe_probe_at"
        case error
    }
}

struct SnapshotSummary: Codable, Equatable, Sendable {
    let configuredAccounts: Int
    let enabledAccounts: Int
    let usableNow: Int
    let statusCounts: StatusCounts
    let capacityBasis: CapacityBasis
    let windowAggregates: WindowAggregates
    let nextUsefulCapacityAt: String?
    let nextUsefulCapacityLabel: String?

    enum CodingKeys: String, CodingKey {
        case configuredAccounts = "configured_accounts"
        case enabledAccounts = "enabled_accounts"
        case usableNow = "usable_now"
        case statusCounts = "status_counts"
        case capacityBasis = "capacity_basis"
        case windowAggregates = "window_aggregates"
        case nextUsefulCapacityAt = "next_useful_capacity_at"
        case nextUsefulCapacityLabel = "next_useful_capacity_label"
    }
}

struct StatusCounts: Codable, Equatable, Sendable {
    let available: Int
    let fiveHourLimited: Int
    let weeklyLimited: Int
    let authInvalid: Int
    let disabled: Int
    let unknown: Int

    enum CodingKeys: String, CodingKey {
        case available
        case fiveHourLimited = "five_hour_limited"
        case weeklyLimited = "weekly_limited"
        case authInvalid = "auth_invalid"
        case disabled
        case unknown
    }
}

struct CapacityBasis: Codable, Equatable, Sendable {
    let key: String?
    let label: String?
    let reportingAccounts: Int
    let eligibleAccounts: Int
    let measurementStatus: String?

    enum CodingKeys: String, CodingKey {
        case key
        case label
        case reportingAccounts = "reporting_accounts"
        case eligibleAccounts = "eligible_accounts"
        case measurementStatus = "measurement_status"
    }
}

struct WindowAggregates: Codable, Equatable, Sendable {
    let fiveHour: WindowAggregate
    let weekly: WindowAggregate

    enum CodingKeys: String, CodingKey {
        case fiveHour = "five_hour"
        case weekly
    }
}

struct WindowAggregate: Codable, Equatable, Sendable {
    let measurementStatus: String?
    let reportingAccounts: Int?
    let unknownAccounts: Int?
    let remainingPoints: Double?
    let maximumKnownPoints: Double?
    let remainingPercent: Double?

    enum CodingKeys: String, CodingKey {
        case measurementStatus = "measurement_status"
        case reportingAccounts = "reporting_accounts"
        case unknownAccounts = "unknown_accounts"
        case remainingPoints = "remaining_points"
        case maximumKnownPoints = "maximum_known_points"
        case remainingPercent = "remaining_percent"
    }
}

struct CapacityWarning: Codable, Equatable, Identifiable, Sendable {
    let severity: String?
    let code: String?
    let accountLabel: String?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case severity
        case code
        case accountLabel = "account_label"
        case message
    }

    var id: String {
        [severity, code, accountLabel, message].compactMap { $0 }.joined(separator: "|")
    }
}

struct CodexAccount: Codable, Equatable, Identifiable, Sendable {
    let label: String
    let enabled: Bool
    let routingPreferred: Bool
    let planType: String?
    let status: String
    let statusReason: String
    let authValid: Bool?
    let selectableNow: Bool
    let safetyFloorActive: Bool
    let fiveHour: UsageWindow
    let weekly: UsageWindow
    let lastProbeAt: String?
    let stale: Bool
    let staleSeconds: Int?
    let probeError: String?

    enum CodingKeys: String, CodingKey {
        case label
        case enabled
        case routingPreferred = "routing_preferred"
        case planType = "plan_type"
        case status
        case statusReason = "status_reason"
        case authValid = "auth_valid"
        case selectableNow = "selectable_now"
        case safetyFloorActive = "safety_floor_active"
        case fiveHour = "five_hour"
        case weekly
        case lastProbeAt = "last_probe_at"
        case stale
        case staleSeconds = "stale_seconds"
        case probeError = "probe_error"
    }

    var id: String { label }

    static func fixture(
        label: String,
        status: String,
        reason: String,
        preferred: Bool,
        fiveRemaining: Double,
        fiveReset: Date,
        weeklyRemaining: Double,
        weeklyReset: Date
    ) -> CodexAccount {
        CodexAccount(
            label: label,
            enabled: true,
            routingPreferred: preferred,
            planType: "pro",
            status: status,
            statusReason: reason,
            authValid: status != "auth_invalid",
            selectableNow: status == "available",
            safetyFloorActive: status == "five_hour_limited" && fiveRemaining > 0,
            fiveHour: UsageWindow.fixture(
                remaining: fiveRemaining, reset: fiveReset, seconds: 18_000
            ),
            weekly: UsageWindow.fixture(
                remaining: weeklyRemaining, reset: weeklyReset, seconds: 604_800
            ),
            lastProbeAt: ServerDateParser.string(Date().addingTimeInterval(-32)),
            stale: false,
            staleSeconds: 32,
            probeError: nil
        )
    }
}

struct UsageWindow: Codable, Equatable, Sendable {
    let reported: Bool
    let usedPercent: Double?
    let remainingPercent: Double?
    let resetAt: String?
    let resetInSeconds: Int?
    let windowSeconds: Int?

    enum CodingKeys: String, CodingKey {
        case reported
        case usedPercent = "used_percent"
        case remainingPercent = "remaining_percent"
        case resetAt = "reset_at"
        case resetInSeconds = "reset_in_seconds"
        case windowSeconds = "window_seconds"
    }

    var resetDate: Date? {
        resetAt.flatMap(ServerDateParser.parse)
    }

    static func fixture(remaining: Double, reset: Date, seconds: Int) -> UsageWindow {
        UsageWindow(
            reported: true,
            usedPercent: 100 - remaining,
            remainingPercent: remaining,
            resetAt: ServerDateParser.string(reset),
            resetInSeconds: max(0, Int(reset.timeIntervalSinceNow)),
            windowSeconds: seconds
        )
    }
}

struct RefreshPolicy: Codable, Equatable, Sendable {
    let manualMinIntervalSeconds: Int
    let recommendedBackgroundIntervalSeconds: Int

    enum CodingKeys: String, CodingKey {
        case manualMinIntervalSeconds = "manual_min_interval_seconds"
        case recommendedBackgroundIntervalSeconds = "recommended_background_interval_seconds"
    }
}

struct RefreshResponse: Codable, Sendable {
    let schemaVersion: Int
    let probeStarted: Bool
    let reason: String?
    let retryAfterSeconds: Int?
    let snapshot: CodexSnapshot

    enum CodingKeys: String, CodingKey {
        case schemaVersion = "schema_version"
        case probeStarted = "probe_started"
        case reason
        case retryAfterSeconds = "retry_after_seconds"
        case snapshot
    }
}

enum ServerDateParser {
    private static let fractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let whole: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    static func parse(_ value: String) -> Date? {
        fractional.date(from: value) ?? whole.date(from: value)
    }

    static func string(_ date: Date) -> String {
        fractional.string(from: date)
    }
}
