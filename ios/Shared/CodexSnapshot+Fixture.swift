import Foundation

extension CodexSnapshot {
    internal static var fixture: Self {
        let now: Date = .init()
        let probeSecondsAgo: TimeInterval = 32
        let probeAgeSeconds: Int = 32
        let accountCount: Int = 4
        let usableNow: Int = 2
        let limitedCount: Int = 1
        let manualMinIntervalSeconds: Int = 60
        let recommendedBackgroundIntervalSeconds: Int = 900
        let fiveHourWindowSeconds: Int = 18_000
        let weeklyWindowSeconds: Int = 604_800
        let fullPercent: Double = 100
        let fiveHourRemainingPoints: Double = 213
        let weeklyRemainingPoints: Double = 268
        let maximumKnownPoints: Double = 400
        let fiveHourRemainingPercent: Double = 53.3
        let weeklyRemainingPercent: Double = 67
        let reserveResetSeconds: TimeInterval = 2_520
        let primaryResetSeconds: TimeInterval = 4_180
        let primaryWeeklyResetSeconds: TimeInterval = 259_200
        let reserveWeeklyResetSeconds: TimeInterval = 345_600
        let operationsResetSeconds: TimeInterval = 7_200
        let operationsWeeklyResetSeconds: TimeInterval = 432_000
        let researchResetSeconds: TimeInterval = 10_800
        let researchWeeklyResetSeconds: TimeInterval = 172_800
        let primaryFiveRemaining: Double = 84
        let primaryWeeklyRemaining: Double = 72
        let reserveFiveRemaining: Double = 10
        let reserveWeeklyRemaining: Double = 64
        let operationsFiveRemaining: Double = 59
        let operationsWeeklyRemaining: Double = 81
        let researchFiveRemaining: Double = 60
        let researchWeeklyRemaining: Double = 51
        let availableStatus: String = "available"
        let fiveHourLimitedStatus: String = "five_hour_limited"
        let authInvalidStatus: String = "auth_invalid"
        let criticalSeverity: String = "critical"
        let completeStatus: String = "complete"
        let fiveHourKey: String = "five_hour"
        let fiveHourLabel: String = "Five-hour"
        let reserveLabel: String = "Team reserve"
        let proPlanType: String = "pro"
        let selectableReason: String = "Selectable now"
        let probeAt: String = ServerDateParser.string(now.addingTimeInterval(-probeSecondsAgo))

        let primaryAccount: CodexAccount = .init(
            label: "Primary",
            enabled: true,
            routingPreferred: true,
            planType: proPlanType,
            status: availableStatus,
            statusReason: selectableReason,
            selectableNow: true,
            safetyFloorActive: false,
            fiveHour: UsageWindow(
                reported: true,
                usedPercent: fullPercent - primaryFiveRemaining,
                remainingPercent: primaryFiveRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(primaryResetSeconds)
                ),
                resetInSeconds: Int(primaryResetSeconds),
                windowSeconds: fiveHourWindowSeconds
            ),
            weekly: UsageWindow(
                reported: true,
                usedPercent: fullPercent - primaryWeeklyRemaining,
                remainingPercent: primaryWeeklyRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(primaryWeeklyResetSeconds)
                ),
                resetInSeconds: Int(primaryWeeklyResetSeconds),
                windowSeconds: weeklyWindowSeconds
            ),
            lastProbeAt: probeAt,
            stale: false,
            staleSeconds: probeAgeSeconds,
            probeError: nil
        )

        let reserveAccount: CodexAccount = .init(
            label: reserveLabel,
            enabled: true,
            routingPreferred: false,
            planType: proPlanType,
            status: fiveHourLimitedStatus,
            statusReason: "Held at broker five-hour safety floor",
            selectableNow: false,
            safetyFloorActive: true,
            fiveHour: UsageWindow(
                reported: true,
                usedPercent: fullPercent - reserveFiveRemaining,
                remainingPercent: reserveFiveRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(reserveResetSeconds)
                ),
                resetInSeconds: Int(reserveResetSeconds),
                windowSeconds: fiveHourWindowSeconds
            ),
            weekly: UsageWindow(
                reported: true,
                usedPercent: fullPercent - reserveWeeklyRemaining,
                remainingPercent: reserveWeeklyRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(reserveWeeklyResetSeconds)
                ),
                resetInSeconds: Int(reserveWeeklyResetSeconds),
                windowSeconds: weeklyWindowSeconds
            ),
            lastProbeAt: probeAt,
            stale: false,
            staleSeconds: probeAgeSeconds,
            probeError: nil
        )

        let operationsAccount: CodexAccount = .init(
            label: "Operations",
            enabled: true,
            routingPreferred: false,
            planType: proPlanType,
            status: availableStatus,
            statusReason: selectableReason,
            selectableNow: true,
            safetyFloorActive: false,
            fiveHour: UsageWindow(
                reported: true,
                usedPercent: fullPercent - operationsFiveRemaining,
                remainingPercent: operationsFiveRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(operationsResetSeconds)
                ),
                resetInSeconds: Int(operationsResetSeconds),
                windowSeconds: fiveHourWindowSeconds
            ),
            weekly: UsageWindow(
                reported: true,
                usedPercent: fullPercent - operationsWeeklyRemaining,
                remainingPercent: operationsWeeklyRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(operationsWeeklyResetSeconds)
                ),
                resetInSeconds: Int(operationsWeeklyResetSeconds),
                windowSeconds: weeklyWindowSeconds
            ),
            lastProbeAt: probeAt,
            stale: false,
            staleSeconds: probeAgeSeconds,
            probeError: nil
        )

        let researchAccount: CodexAccount = .init(
            label: "Research",
            enabled: true,
            routingPreferred: false,
            planType: proPlanType,
            status: authInvalidStatus,
            statusReason: "Login or token refresh required",
            selectableNow: false,
            safetyFloorActive: false,
            fiveHour: UsageWindow(
                reported: true,
                usedPercent: fullPercent - researchFiveRemaining,
                remainingPercent: researchFiveRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(researchResetSeconds)
                ),
                resetInSeconds: Int(researchResetSeconds),
                windowSeconds: fiveHourWindowSeconds
            ),
            weekly: UsageWindow(
                reported: true,
                usedPercent: fullPercent - researchWeeklyRemaining,
                remainingPercent: researchWeeklyRemaining,
                resetAt: ServerDateParser.string(
                    now.addingTimeInterval(researchWeeklyResetSeconds)
                ),
                resetInSeconds: Int(researchWeeklyResetSeconds),
                windowSeconds: weeklyWindowSeconds
            ),
            lastProbeAt: probeAt,
            stale: false,
            staleSeconds: probeAgeSeconds,
            probeError: nil
        )

        return Self(
            schemaVersion: 1,
            generatedAt: ServerDateParser.string(now),
            source: SnapshotSource(
                stale: false,
                staleAccountCount: 0,
                newestAccountProbeAt: probeAt,
                lastSafeProbeAt: probeAt,
                error: nil
            ),
            summary: SnapshotSummary(
                configuredAccounts: accountCount,
                enabledAccounts: accountCount,
                usableNow: usableNow,
                statusCounts: StatusCounts(
                    available: usableNow,
                    fiveHourLimited: limitedCount,
                    weeklyLimited: 0,
                    authInvalid: limitedCount,
                    disabled: 0,
                    unknown: 0
                ),
                capacityBasis: CapacityBasis(
                    key: fiveHourKey,
                    label: fiveHourLabel,
                    reportingAccounts: accountCount,
                    eligibleAccounts: accountCount,
                    measurementStatus: completeStatus
                ),
                windowAggregates: WindowAggregates(
                    fiveHour: WindowAggregate(
                        measurementStatus: completeStatus,
                        reportingAccounts: accountCount,
                        unknownAccounts: 0,
                        remainingPoints: fiveHourRemainingPoints,
                        maximumKnownPoints: maximumKnownPoints,
                        remainingPercent: fiveHourRemainingPercent
                    ),
                    weekly: WindowAggregate(
                        measurementStatus: completeStatus,
                        reportingAccounts: accountCount,
                        unknownAccounts: 0,
                        remainingPoints: weeklyRemainingPoints,
                        maximumKnownPoints: maximumKnownPoints,
                        remainingPercent: weeklyRemainingPercent
                    )
                ),
                nextUsefulCapacityAt: ServerDateParser.string(
                    now.addingTimeInterval(reserveResetSeconds)
                ),
                nextUsefulCapacityLabel: reserveLabel
            ),
            warnings: [
                CapacityWarning(
                    severity: criticalSeverity,
                    code: authInvalidStatus,
                    accountLabel: "Research",
                    message: "Account needs login or token refresh"
                )
            ],
            accounts: [primaryAccount, reserveAccount, operationsAccount, researchAccount],
            refreshPolicy: RefreshPolicy(
                manualMinIntervalSeconds: manualMinIntervalSeconds,
                recommendedBackgroundIntervalSeconds: recommendedBackgroundIntervalSeconds
            )
        )
    }
}
