import SwiftUI

internal struct WarningStrip: View {
    internal enum Style {
        internal static let stackSpacing: CGFloat = 9
        internal static let rowSpacing: CGFloat = 10
        internal static let textSpacing: CGFloat = 2
        internal static let padding: CGFloat = 15
        internal static let cornerRadius: CGFloat = 16
        internal static let maximumWarnings: Int = 3
    }

    internal let warnings: [CapacityWarning]

    private var important: [CapacityWarning] {
        warnings.filter { warning in
            warning.severity == "critical" || warning.severity == "warning"
        }
    }

    internal var body: some View {
        if !important.isEmpty {
            VStack(alignment: .leading, spacing: Style.stackSpacing) {
                SectionHeading(title: "Attention", detail: countDescription)
                ForEach(important.prefix(Style.maximumWarnings)) { warning in
                    WarningRow(warning: warning)
                }
            }
            .padding(Style.padding)
            .background(
                Color(uiColor: .secondarySystemGroupedBackground),
                in: RoundedRectangle(cornerRadius: Style.cornerRadius)
            )
        }
    }

    private var countDescription: String {
        let plural: String = important.count == 1 ? "" : "s"
        return "\(important.count) warning\(plural)"
    }
}
