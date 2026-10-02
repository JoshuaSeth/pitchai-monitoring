import SwiftUI

internal struct MetricPill: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 3
        internal static let titleFontSize: CGFloat = 9
        internal static let tracking: CGFloat = 0.7
        internal static let titleOpacity: Double = 0.5
        internal static let horizontalPadding: CGFloat = 12
        internal static let verticalPadding: CGFloat = 10
        internal static let cornerRadius: CGFloat = 12
        internal static let fillOpacity: Double = 0.07
        internal static let minimumScale: CGFloat = 0.72
    }

    internal let title: String
    internal let value: String

    internal var body: some View {
        VStack(alignment: .leading, spacing: Style.stackSpacing) {
            Text(title.uppercased())
                .font(.system(size: Style.titleFontSize, weight: .bold))
                .tracking(Style.tracking)
                .foregroundStyle(.white.opacity(Style.titleOpacity))
            Text(value)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(1)
                .minimumScaleFactor(Style.minimumScale)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Style.horizontalPadding)
        .padding(.vertical, Style.verticalPadding)
        .background(
            .white.opacity(Style.fillOpacity),
            in: RoundedRectangle(cornerRadius: Style.cornerRadius)
        )
    }
}
