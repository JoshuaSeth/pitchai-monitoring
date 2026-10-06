import SwiftUI

internal struct OpenCodeSection: View {
    internal enum Style {
        internal static let sectionSpacing: CGFloat = 10
    }

    internal let subscriptions: OpenCodeSubscriptionSet

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.sectionSpacing) {
            SectionHeading(title: "OpenCode subscriptions", detail: readiness)
            if let error = subscriptions.error {
                ServiceMessageCard(
                    symbol: "exclamationmark.triangle.fill",
                    title: "OpenCode status unavailable",
                    message: error,
                    tint: .orange
                )
            }
            ForEach(subscriptions.accounts) { subscription in
                OpenCodeSubscriptionCard(subscription: subscription)
            }
            Text(footnote)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }

    private var readiness: String {
        let summary: OpenCodeSummary = subscriptions.summary
        return "\(summary.ready) of \(summary.subscriptions) ready"
    }

    private var footnote: String {
        let freshness: String = CapacityFormatting.updated(subscriptions.generatedDate)
        let staleness: String = subscriptions.stale ? "Stale · " : ""
        return staleness + freshness
            + ". Monthly windows renew per subscription. OpenCode Go has no banked resets."
    }
}
