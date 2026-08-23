import Foundation

enum CapacityFormatting {
    static func percent(_ value: Double?) -> String {
        guard let value else { return "—" }
        return value.formatted(.number.precision(.fractionLength(value.rounded() == value ? 0 : 1))) + "%"
    }

    static func points(_ value: Double?) -> String {
        guard let value else { return "—" }
        return value.formatted(.number.precision(.fractionLength(value.rounded() == value ? 0 : 1)))
    }

    static func relative(_ value: String?) -> String {
        guard let value, let date = ServerDateParser.parse(value) else { return "Not reported" }
        if date <= Date() { return "Reset due" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return "Resets " + formatter.localizedString(for: date, relativeTo: Date())
    }

    static func updated(_ date: Date?) -> String {
        guard let date else { return "Update time unavailable" }
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .short
        return "Updated " + formatter.localizedString(for: date, relativeTo: Date())
    }

    static func statusTitle(_ status: String) -> String {
        switch status {
        case "available": "Ready"
        case "five_hour_limited": "5-hour limited"
        case "weekly_limited": "Weekly limited"
        case "auth_invalid": "Login needed"
        case "disabled": "Disabled"
        default: "Unknown"
        }
    }

    static func statusSymbol(_ status: String) -> String {
        switch status {
        case "available": "checkmark.circle.fill"
        case "five_hour_limited": "clock.badge.exclamationmark.fill"
        case "weekly_limited": "calendar.badge.exclamationmark"
        case "auth_invalid": "person.crop.circle.badge.exclamationmark"
        case "disabled": "pause.circle.fill"
        default: "questionmark.circle.fill"
        }
    }
}
