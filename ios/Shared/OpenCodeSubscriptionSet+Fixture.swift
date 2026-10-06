import Foundation

extension OpenCodeSubscriptionSet {
    internal static var fixture: Self {
        let now: Date = .init()
        let rollingResetSeconds: TimeInterval = 18_000
        let weeklyResetSeconds: TimeInterval = 518_400
        let monthlyResetSeconds: TimeInterval = 1_382_400
        let cooldownSeconds: TimeInterval = 518_400
        let infoPosition: Int = 1
        let salesPosition: Int = 2
        let subscriptionCount: Int = 2
        let monthlyReset: String = ServerDateParser.string(
            now.addingTimeInterval(monthlyResetSeconds)
        )
        let rolling: UsageWindow = window(used: 0, resetIn: rollingResetSeconds, now: now)
        let weekly: UsageWindow = window(used: 0, resetIn: weeklyResetSeconds, now: now)
        let monthly: UsageWindow = window(used: 100, resetIn: monthlyResetSeconds, now: now)
        let windows: OpenCodeWindows = .init(rolling: rolling, weekly: weekly, monthly: monthly)
        let info: OpenCodeSubscription = .init(
            label: "info@pitchai.net",
            position: infoPosition,
            status: "limited",
            limitedBy: ["monthly"],
            availableAt: monthlyReset,
            windows: windows,
            bridgeLastStatus: nil,
            bridgeCooldownUntil: nil,
            error: nil
        )
        let sales: OpenCodeSubscription = .init(
            label: "sales@pitchai.net",
            position: salesPosition,
            status: "limited",
            limitedBy: ["monthly"],
            availableAt: monthlyReset,
            windows: windows,
            bridgeLastStatus: nil,
            bridgeCooldownUntil: ServerDateParser.string(now.addingTimeInterval(cooldownSeconds)),
            error: nil
        )
        return Self(
            schemaVersion: 1,
            generatedAt: ServerDateParser.string(now),
            stale: false,
            error: nil,
            summary: OpenCodeSummary(
                subscriptions: subscriptionCount,
                ready: 0,
                limited: subscriptionCount,
                nextAvailableAt: monthlyReset
            ),
            accounts: [info, sales]
        )
    }

    private static func window(
        used: Double,
        resetIn seconds: TimeInterval,
        now: Date
    ) -> UsageWindow {
        let fullPercent: Double = 100
        return UsageWindow(
            reported: true,
            usedPercent: used,
            remainingPercent: fullPercent - used,
            resetAt: ServerDateParser.string(now.addingTimeInterval(seconds)),
            resetInSeconds: Int(seconds),
            windowSeconds: nil
        )
    }
}
