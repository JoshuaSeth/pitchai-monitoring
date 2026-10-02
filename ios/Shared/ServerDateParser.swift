import Foundation

internal enum ServerDateParser {
    private static let fractionalSecondsStyle: Date.ISO8601FormatStyle = .init(
        includingFractionalSeconds: true
    )

    private static let wholeSecondsStyle: Date.ISO8601FormatStyle = .init()

    internal static func parse(_ value: String) -> Date? {
        if let date: Date = parse(value, with: fractionalSecondsStyle) {
            return date
        }
        return parse(value, with: wholeSecondsStyle)
    }

    internal static func string(_ date: Date) -> String {
        fractionalSecondsStyle.format(date)
    }

    private static func parse(_ value: String, with style: Date.ISO8601FormatStyle) -> Date? {
        do {
            return try style.parse(value)
        } catch {
            return nil
        }
    }
}
