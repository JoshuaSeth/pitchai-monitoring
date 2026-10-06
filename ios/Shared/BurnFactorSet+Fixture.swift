import Foundation

extension BurnFactorSet {
    internal static var fixture: Self {
        let codexShort: Double = 0.54
        let codexLong: Double = 36.96
        let claudeShort: Double = 0.08
        let claudeLong: Double = 0.34
        let claudeDemand: Double = 140
        let claudeAvailable: Double = 416
        let pointsUnit: String = "points"
        let shortTermRolling: String = "30m"
        let longTermRolling: String = "24h"
        let codexShortView: BurnFactorResult = view(
            shortTermRolling,
            factor: codexShort,
            status: "limited",
            lowerBound: true
        )
        let codexLongView: BurnFactorResult = view(
            longTermRolling,
            factor: codexLong,
            status: "short"
        )
        let claudeShortView: BurnFactorResult = view(
            shortTermRolling,
            factor: claudeShort,
            status: "good",
            lowerBound: true
        )
        let claudeLongView: BurnFactorResult = claudeView(
            factor: claudeLong,
            demand: claudeDemand,
            available: claudeAvailable
        )
        let blockedShort: BurnFactorResult = view(shortTermRolling, factor: nil, status: "short")
        let blockedLong: BurnFactorResult = view(longTermRolling, factor: nil, status: "short")
        let codex: BurnFactorPool = .init(
            key: "openai",
            label: "Codex",
            unit: pointsUnit,
            balanceUSD: nil,
            results: [codexShortView, codexLongView]
        )
        let claude: BurnFactorPool = .init(
            key: "anthropic",
            label: "Claude",
            unit: pointsUnit,
            balanceUSD: nil,
            results: [claudeShortView, claudeLongView]
        )
        let openCode: BurnFactorPool = .init(
            key: "opencode",
            label: "OpenCode",
            unit: pointsUnit,
            balanceUSD: nil,
            results: [blockedShort, blockedLong]
        )
        let deepSeek: BurnFactorPool = .init(
            key: "deepseek",
            label: "DeepSeek",
            unit: BurnFactorPool.moneyUnit,
            balanceUSD: 0,
            results: [blockedShort, blockedLong]
        )
        return Self(
            schemaVersion: 1,
            generatedAt: ServerDateParser.string(Date()),
            pools: [codex, claude, openCode, deepSeek]
        )
    }

    private static func view(
        _ rolling: String,
        factor: Double?,
        status: String,
        lowerBound: Bool = false
    ) -> BurnFactorResult {
        let shortTerm: Bool = rolling == "30m"
        return BurnFactorResult(
            rolling: rolling,
            horizon: shortTerm ? BurnFactorPool.shortTermHorizon : BurnFactorPool.longTermHorizon,
            factor: factor,
            status: status,
            lowerBound: lowerBound,
            runwayHours: nil,
            burnPerHour: nil,
            demand: nil,
            available: nil,
            margin: nil,
            blockedUntil: nil
        )
    }

    private static func claudeView(
        factor: Double,
        demand: Double,
        available: Double
    ) -> BurnFactorResult {
        BurnFactorResult(
            rolling: "24h",
            horizon: BurnFactorPool.longTermHorizon,
            factor: factor,
            status: "good",
            lowerBound: true,
            runwayHours: nil,
            burnPerHour: 1,
            demand: demand,
            available: available,
            margin: available - demand,
            blockedUntil: nil
        )
    }
}
