import SwiftUI

internal struct WarningRow: View {
    internal enum Style {
        internal static let rowSpacing: CGFloat = 10
        internal static let textSpacing: CGFloat = 2
    }

    internal let warning: CapacityWarning

    private var isCritical: Bool {
        warning.severity == "critical"
    }

    internal var body: some View {
        HStack(alignment: .top, spacing: Style.rowSpacing) {
            Image(
                systemName: isCritical
                    ? "exclamationmark.octagon.fill" : "exclamationmark.triangle.fill"
            )
            .foregroundStyle(isCritical ? .red : .orange)
            VStack(alignment: .leading, spacing: Style.textSpacing) {
                if let label = warning.accountLabel {
                    Text(label)
                        .font(.caption.weight(.semibold))
                }
                Text(warning.message ?? "Broker warning")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
    }
}
