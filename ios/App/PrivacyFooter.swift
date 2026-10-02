import SwiftUI

internal struct PrivacyFooter: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 6
        internal static let topPadding: CGFloat = 4
        internal static let horizontalPadding: CGFloat = 24
    }

    internal var body: some View {
        VStack(spacing: Style.stackSpacing) {
            Label("Read-only · Verified by App Attest", systemImage: "lock.shield.fill")
                .font(.caption.weight(.semibold))
            Text(
                "Only redacted capacity and account-state fields are cached for the Watch and widgets."
            )
            .font(.caption2)
            .multilineTextAlignment(.center)
        }
        .foregroundStyle(.secondary)
        .padding(.top, Style.topPadding)
        .padding(.horizontal, Style.horizontalPadding)
    }
}
