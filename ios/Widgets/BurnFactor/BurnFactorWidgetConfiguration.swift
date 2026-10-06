import SwiftUI
import WidgetKit

internal enum BurnFactorWidgetConfiguration {
    /// Plain `String` names: an interpolated literal would become a `LocalizedStringKey` with
    /// arguments, which WidgetKit traps on while registering the widget.
    internal static func pool(_ choice: BurnFactorPoolChoice) -> some WidgetConfiguration {
        let name: String = choice.displayName + " burn factor"
        let summary: String =
            choice.displayName + ": the last 24 h of burn against the next 6 days."
        return StaticConfiguration(kind: choice.kind, provider: BurnFactorProvider()) { entry in
            BurnFactorWidgetView(entry: entry, choice: choice)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName(name)
        .description(summary)
        .supportedFamilies(BurnFactorWidgetStyle.poolFamilies)
    }
}
