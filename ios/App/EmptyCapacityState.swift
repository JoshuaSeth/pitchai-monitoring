import SwiftUI

internal struct EmptyCapacityState: View {
    internal enum Style {
        internal static let minimumHeight: CGFloat = 430
    }

    internal let message: String?
    internal let isLoading: Bool

    internal var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: symbol)
        } description: {
            Text(message ?? "Establishing a hardware-backed connection to the capacity service.")
        }
        .frame(minHeight: Style.minimumHeight)
    }

    private var title: String {
        isLoading ? "Verifying this iPhone" : "Live status unavailable"
    }

    private var symbol: String {
        isLoading ? "checkmark.shield" : "wifi.exclamationmark"
    }
}
