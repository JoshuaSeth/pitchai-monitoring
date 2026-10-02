import SwiftUI

internal struct WatchHero: View {
    internal enum Style {
        internal static let rowSpacing: CGFloat = 10
        internal static let textSpacing: CGFloat = 2
        internal static let gaugeSize: CGFloat = 54
        internal static let stateFontSize: CGFloat = 9
        internal static let cornerRadius: CGFloat = 14
        internal static let padding: CGFloat = 10
        internal static let fullPercent: Double = 100
        internal static let gradientTopOpacity: Double = 0.2
        internal static let gradientBottomOpacity: Double = 0.08
    }

    internal let snapshot: CodexSnapshot

    private var percentage: Double {
        snapshot.selectedAggregate?.remainingPercent ?? 0
    }

    internal var body: some View {
        HStack(spacing: Style.rowSpacing) {
            gauge
            summary
            Spacer(minLength: 0)
        }
        .padding(Style.padding)
        .background(backgroundGradient, in: RoundedRectangle(cornerRadius: Style.cornerRadius))
    }

    private var gauge: some View {
        Gauge(value: min(max(percentage, 0), Style.fullPercent), in: 0...Style.fullPercent) {
            EmptyView()
        } currentValueLabel: {
            Text(CapacityFormatting.percent(percentage))
                .font(.caption2.bold())
                .monospacedDigit()
        }
        .gaugeStyle(.accessoryCircularCapacity)
        .tint(Gradient(colors: [.mint, .cyan]))
        .frame(width: Style.gaugeSize, height: Style.gaugeSize)
    }

    private var summary: some View {
        VStack(alignment: .leading, spacing: Style.textSpacing) {
            Text("\(snapshot.summary.usableNow) of \(snapshot.summary.enabledAccounts)")
                .font(.title3.bold())
                .monospacedDigit()
            Text("accounts ready")
                .font(.caption2)
                .foregroundStyle(.secondary)
            Label(stateText, systemImage: stateSymbol)
                .font(.system(size: Style.stateFontSize, weight: .semibold))
                .foregroundStyle(stateTint)
        }
    }

    private var stateText: String {
        if snapshot.isStale {
            return "Stale"
        }
        if snapshot.summary.usableNow == 0 {
            return "No capacity"
        }
        if snapshot.importantWarningCount > 0 {
            return "Attention"
        }
        return "Verified"
    }

    private var stateSymbol: String {
        if snapshot.isStale {
            return "clock.badge.exclamationmark"
        }
        return snapshot.requiresAttention
            ? "exclamationmark.triangle.fill" : "checkmark.shield.fill"
    }

    private var stateTint: Color {
        if snapshot.summary.usableNow == 0 {
            return .red
        }
        return snapshot.requiresAttention ? .orange : .green
    }

    private var backgroundGradient: LinearGradient {
        LinearGradient(
            colors: [topColor, bottomColor],
            startPoint: .topLeading,
            endPoint: .bottomTrailing
        )
    }

    private var topColor: Color {
        .cyan.opacity(Style.gradientTopOpacity)
    }

    private var bottomColor: Color {
        .blue.opacity(Style.gradientBottomOpacity)
    }
}
