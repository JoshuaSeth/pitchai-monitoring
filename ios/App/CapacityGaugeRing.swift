import SwiftUI

internal struct CapacityGaugeRing: View {
    internal enum Style {
        internal static let trackOpacity: Double = 0.14
        internal static let lineWidth: CGFloat = 10
        internal static let ringSize: CGFloat = 106
        internal static let rotationDegrees: Double = -90
        internal static let percentFontSize: CGFloat = 22
        internal static let labelOpacity: Double = 0.65
        internal static let fullPercent: Double = 100
    }

    internal let percentage: Double

    internal var body: some View {
        ZStack {
            Circle()
                .stroke(.white.opacity(Style.trackOpacity), lineWidth: Style.lineWidth)
            Circle()
                .trim(from: 0, to: trimEnd)
                .stroke(trackGradient, style: strokeStyle)
                .rotationEffect(.degrees(Style.rotationDegrees))
            labels
        }
        .frame(width: Style.ringSize, height: Style.ringSize)
    }

    private var labels: some View {
        VStack(spacing: 0) {
            Text(CapacityFormatting.percent(percentage))
                .font(.system(size: Style.percentFontSize, weight: .bold, design: .rounded))
                .monospacedDigit()
            Text("remaining")
                .font(.caption2)
                .foregroundStyle(.white.opacity(Style.labelOpacity))
        }
    }

    private var trimEnd: Double {
        min(max(percentage / Style.fullPercent, 0), 1)
    }

    private var trackGradient: AngularGradient {
        AngularGradient(colors: [.mint, .cyan, .blue], center: .center)
    }

    private var strokeStyle: StrokeStyle {
        StrokeStyle(lineWidth: Style.lineWidth, lineCap: .round)
    }
}
