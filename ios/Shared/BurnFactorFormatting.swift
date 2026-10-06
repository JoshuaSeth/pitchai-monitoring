import SwiftUI

internal enum BurnFactorFormatting {
    internal static let gaugeMaximum: Double = 2
    internal static let shortStatus: String = "short"
    internal static let limitedStatus: String = "limited"

    private static let unavailable: String = "—"
    private static let infinity: String = "∞"
    private static let lowerBoundPrefix: String = "≥"
    private static let largeFactorThreshold: Double = 10
    private static let preciseFractionLength: Int = 2
    private static let compactFractionLength: Int = 1
    private static let minutesPerHour: Double = 60
    private static let hoursPerDay: Double = 24
    private static let dayThresholdHours: Double = 48

    internal static var gaugeGradient: Gradient {
        Gradient(colors: [.green, .yellow, .orange, .red])
    }

    /// Full factor text such as `0.34`, `≥0.08`, `42` or `∞`.
    internal static func factor(_ result: BurnFactorResult?) -> String {
        text(result, fractionLength: preciseFractionLength)
    }

    /// Short factor text for complications: one decimal below 10, whole numbers above.
    internal static func compactFactor(_ result: BurnFactorResult?) -> String {
        text(result, fractionLength: compactFractionLength)
    }

    /// Factor clamped to the 0...2 gauge range; a shortage without capacity fills the gauge.
    internal static func gaugeValue(_ result: BurnFactorResult?) -> Double {
        guard let result else {
            return 0
        }
        guard let factor = result.factor else {
            return result.status == shortStatus ? gaugeMaximum : 0
        }
        return min(max(factor, 0), gaugeMaximum)
    }

    internal static func statusTitle(_ status: String) -> String {
        switch status {
        case "good":
            return "Margin"

        case "limited":
            return "At limit"

        case "short":
            return "Shortage"

        case "tight":
            return "Tight"

        default:
            return "Unknown"
        }
    }

    internal static func statusSymbol(_ status: String) -> String {
        switch status {
        case "good":
            return "checkmark.circle.fill"

        case "limited":
            return "diamond.fill"

        case "short":
            return "exclamationmark.triangle.fill"

        case "tight":
            return "exclamationmark.circle.fill"

        default:
            return "questionmark.circle.fill"
        }
    }

    internal static func tint(_ status: String) -> Color {
        switch status {
        case "good":
            return .green

        case "limited":
            return .orange

        case "short":
            return .red

        case "tight":
            return .yellow

        default:
            return .gray
        }
    }

    internal static func runway(_ result: BurnFactorResult?) -> String {
        guard let result else {
            return unavailable
        }
        if result.status == limitedStatus {
            return "Accounts at their limit"
        }
        guard let hours = result.runwayHours else {
            return result.status == shortStatus ? "No usable capacity" : "Runway beyond 14 days"
        }
        return "Runs short in " + duration(hours)
    }

    /// Runway text, or "Balance empty" for a prepaid pool with nothing left to spend.
    internal static func outlook(_ result: BurnFactorResult?, money: Bool) -> String {
        if money, (result?.available ?? 0) <= 0 {
            return "Balance empty · top up to resume"
        }
        return runway(result)
    }

    internal static func amount(_ value: Double?, money: Bool) -> String {
        guard let value else {
            return unavailable
        }
        if money {
            return value.formatted(.currency(code: "USD"))
        }
        return CapacityFormatting.points(value.rounded()) + " pts"
    }

    private static func duration(_ hours: Double) -> String {
        if hours < 1 {
            return "\(Int((hours * minutesPerHour).rounded())) min"
        }
        if hours < dayThresholdHours {
            return hours.formatted(.number.precision(.fractionLength(compactFractionLength))) + " h"
        }
        let days: Double = hours / hoursPerDay
        return days.formatted(.number.precision(.fractionLength(compactFractionLength))) + " days"
    }

    private static func text(_ result: BurnFactorResult?, fractionLength: Int) -> String {
        guard let result else {
            return unavailable
        }
        guard let factor = result.factor else {
            return result.status == shortStatus ? infinity : unavailable
        }
        let digits: Int = factor >= largeFactorThreshold ? 0 : fractionLength
        let number: String = factor.formatted(.number.precision(.fractionLength(digits)))
        return result.lowerBound && factor < 1 ? lowerBoundPrefix + number : number
    }
}
