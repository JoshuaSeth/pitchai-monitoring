import SwiftUI

internal struct ServiceMessageCard: View {
    internal enum Style {
        internal static let rowSpacing: CGFloat = 11
        internal static let textSpacing: CGFloat = 2
        internal static let padding: CGFloat = 13
        internal static let cornerRadius: CGFloat = 14
        internal static let fillOpacity: Double = 0.09
    }

    internal let symbol: String
    internal let title: String
    internal let message: String
    internal let tint: Color

    internal var body: some View {
        HStack(alignment: .top, spacing: Style.rowSpacing) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: Style.textSpacing) {
                Text(title)
                    .font(.subheadline.weight(.semibold))
                Text(message)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer()
        }
        .padding(Style.padding)
        .background(
            tint.opacity(Style.fillOpacity),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius)
        )
    }
}
