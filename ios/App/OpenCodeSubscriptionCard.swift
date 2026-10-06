import SwiftUI

internal struct OpenCodeSubscriptionCard: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 14
        internal static let rowSpacing: CGFloat = 11
        internal static let textSpacing: CGFloat = 3
        internal static let windowSpacing: CGFloat = 10
        internal static let padding: CGFloat = 16
        internal static let cornerRadius: CGFloat = 18
        internal static let accentCornerRadius: CGFloat = 2
        internal static let accentWidth: CGFloat = 3
        internal static let accentVerticalPadding: CGFloat = 14
        internal static let symbolWidth: CGFloat = 26
    }

    internal let subscription: OpenCodeSubscription

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            header
            windows
            if let note {
                Label(note, systemImage: "clock.arrow.circlepath")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.orange)
            }
        }
        .padding(Style.padding)
        .background(
            Color(uiColor: .secondarySystemGroupedBackground),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius, style: .continuous)
        )
        .overlay(alignment: .leading) {
            RoundedRectangle(cornerRadius: Style.accentCornerRadius)
                .fill(tint)
                .frame(width: Style.accentWidth)
                .padding(.vertical, Style.accentVerticalPadding)
        }
        .accessibilityElement(children: .combine)
    }

    private var tint: Color {
        switch subscription.status {
        case "ready":
            return .green

        case "limited", "cooldown":
            return .orange

        case "auth_invalid":
            return .red

        default:
            return .gray
        }
    }

    private var statusTitle: String {
        switch subscription.status {
        case "ready":
            return "Ready"

        case "limited":
            return "Limit reached · " + subscription.limitedBy.joined(separator: ", ")

        case "cooldown":
            return "Bridge cooldown"

        case "auth_invalid":
            return "Key rejected"

        default:
            return "Status unavailable"
        }
    }

    private var symbol: String {
        subscription.status == "ready" ? "checkmark.circle.fill" : "hourglass"
    }

    private var header: some View {
        HStack(alignment: .top, spacing: Style.rowSpacing) {
            Image(systemName: symbol)
                .font(.title3)
                .foregroundStyle(tint)
                .frame(width: Style.symbolWidth)
            VStack(alignment: .leading, spacing: Style.textSpacing) {
                Text(subscription.label)
                    .font(.headline)
                    .lineLimit(1)
                Text(statusTitle)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(tint)
                Text("OpenCode Go · rotation slot \(subscription.position)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private var windows: some View {
        VStack(spacing: Style.windowSpacing) {
            if let rolling = subscription.windows.rolling {
                CapacityWindowRow(title: "5-hour", window: rolling, tint: tint)
            }
            if let weekly = subscription.windows.weekly {
                CapacityWindowRow(title: "Weekly", window: weekly, tint: .blue)
            }
            if let monthly = subscription.windows.monthly {
                CapacityWindowRow(title: "Monthly", window: monthly, tint: .purple)
            }
        }
    }

    private var note: String? {
        guard subscription.status != "ready" else {
            return nil
        }
        var parts: [String] = []
        if let available = relative(subscription.availableAt) {
            parts.append("Usable again \(available)")
        }
        if let cooldown = relative(subscription.bridgeCooldownUntil) {
            parts.append("bridge cooldown ends \(cooldown)")
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    private func relative(_ value: String?) -> String? {
        guard let value, let date: Date = ServerDateParser.parse(value) else {
            return nil
        }
        let formatter: RelativeDateTimeFormatter = .init()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}
