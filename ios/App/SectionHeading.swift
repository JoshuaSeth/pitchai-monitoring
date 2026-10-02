import SwiftUI

internal struct SectionHeading: View {
    internal let title: String
    internal let detail: String

    internal var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.title3.bold())
            Spacer()
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}
