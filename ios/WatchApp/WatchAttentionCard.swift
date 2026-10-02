import SwiftUI

internal struct WatchAttentionCard: View {
    internal enum Style {
        internal static let padding: CGFloat = 8
        internal static let fillOpacity: Double = 0.12
        internal static let cornerRadius: CGFloat = 10
    }

    internal let text: String
    internal let tint: Color

    internal var body: some View {
        Label(text, systemImage: "exclamationmark.triangle.fill")
            .font(.caption2.weight(.semibold))
            .foregroundStyle(tint)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(Style.padding)
            .background(
                tint.opacity(Style.fillOpacity),
                in: RoundedRectangle(cornerRadius: Style.cornerRadius)
            )
    }
}
