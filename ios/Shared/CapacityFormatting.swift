import Foundation

internal enum CapacityFormatting {
    private static let unavailable: String = "—"
    private static let wholeNumberFractionLength: Int = 0
    private static let roundedNumberFractionLength: Int = 1

    internal static func percent(_ value: Double?) -> String {
        guard let value else {
            return unavailable
        }
        return value.formatted(.number.precision(.fractionLength(fractionLength(for: value)))) + "%"
    }

    internal static func points(_ value: Double?) -> String {
        guard let value else {
            return unavailable
        }
        return value.formatted(.number.precision(.fractionLength(fractionLength(for: value))))
    }

    internal static func relative(_ value: String?) -> String {
        guard let value, let date: Date = ServerDateParser.parse(value) else {
            return "Not reported"
        }
        if date <= Date() {
            return "Reset due"
        }
        let formatter: RelativeDateTimeFormatter = .init()
        formatter.unitsStyle = .abbreviated
        return "Resets " + formatter.localizedString(for: date, relativeTo: Date())
    }

    internal static func updated(_ date: Date?) -> String {
        guard let date else {
            return "Update time unavailable"
        }
        let formatter: RelativeDateTimeFormatter = .init()
        formatter.unitsStyle = .short
        return "Updated " + formatter.localizedString(for: date, relativeTo: Date())
    }

    internal static func statusTitle(_ status: String) -> String {
        switch status {
        case "available":
            return "Ready"

        case "five_hour_limited":
            return "5-hour limited"

        case "weekly_limited":
            return "Weekly limited"

        case "auth_invalid":
            return "Login needed"

        case "disabled":
            return "Disabled"

        default:
            return "Unknown"
        }
    }

    internal static func statusSymbol(_ status: String) -> String {
        switch status {
        case "available":
            return "checkmark.circle.fill"

        case "five_hour_limited":
            return "clock.badge.exclamationmark.fill"

        case "weekly_limited":
            return "calendar.badge.exclamationmark"

        case "auth_invalid":
            return "person.crop.circle.badge.exclamationmark"

        case "disabled":
            return "pause.circle.fill"

        default:
            return "questionmark.circle.fill"
        }
    }

    private static func fractionLength(for value: Double) -> Int {
        value.rounded() == value ? wholeNumberFractionLength : roundedNumberFractionLength
    }
}
