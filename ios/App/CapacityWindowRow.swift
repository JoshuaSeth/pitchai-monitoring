import SwiftUI

internal struct CapacityWindowRow: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 6
        internal static let fullPercent: Double = 100
        internal static let unreportedOpacity: Double = 0.62
    }

    internal let title: String
    internal let window: UsageWindow
    internal let tint: Color

    internal var body: some View {
        VStack(spacing: Style.stackSpacing) {
            measurements
            ProgressView(value: progress)
                .tint(window.reported ? tint : .gray)
        }
        .opacity(window.reported ? 1 : Style.unreportedOpacity)
    }

    private var measurements: some View {
        HStack {
            Text(title)
                .font(.caption.weight(.semibold))
            Spacer()
            Text(CapacityFormatting.percent(window.remainingPercent))
                .font(.caption.weight(.bold))
                .monospacedDigit()
            Text("·")
                .foregroundStyle(.tertiary)
            Text(CapacityFormatting.relative(window.resetAt))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }

    private var progress: Double {
        min(max((window.remainingPercent ?? 0) / Style.fullPercent, 0), 1)
    }
}
