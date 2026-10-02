import SwiftUI

internal struct CapacityHeroSummary: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 7
        internal static let badgeSpacing: CGFloat = 6
        internal static let readyFontSize: CGFloat = 29
        internal static let readinessOpacity: Double = 0.72
        internal static let updatedOpacity: Double = 0.58
    }

    internal let snapshot: CodexSnapshot

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            stateBadge
            Text("\(snapshot.summary.usableNow) ready")
                .font(.system(size: Style.readyFontSize, weight: .bold, design: .rounded))
                .foregroundStyle(.white)
            Text("of \(snapshot.summary.enabledAccounts) enabled accounts")
                .font(.subheadline)
                .foregroundStyle(.white.opacity(Style.readinessOpacity))
            Text(CapacityFormatting.updated(snapshot.generatedDate))
                .font(.caption)
                .foregroundStyle(.white.opacity(Style.updatedOpacity))
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var stateBadge: some View {
        HStack(spacing: Style.badgeSpacing) {
            Image(systemName: stateSymbol)
            Text(stateTitle)
        }
        .font(.caption2.weight(.bold))
        .foregroundStyle(snapshot.isStale ? .orange : .mint)
    }

    private var stateTitle: String {
        snapshot.isStale ? "STALE" : "LIVE · VERIFIED"
    }

    private var stateSymbol: String {
        snapshot.isStale ? "exclamationmark.triangle.fill" : "checkmark.shield.fill"
    }
}
