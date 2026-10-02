import Foundation

internal struct CapacityWarning: Codable, Equatable, Identifiable, Sendable {
    internal enum CodingKeys: String, CodingKey {
        case accountLabel = "account_label"
        case code = "code"
        case message = "message"
        case severity = "severity"
    }

    private static let identifierSeparator: String = "|"

    internal let severity: String?
    internal let code: String?
    internal let accountLabel: String?
    internal let message: String?

    internal var id: String {
        let components: [String?] = [severity, code, accountLabel, message]
        let identifiers: [String] = components.compactMap { component in component }
        return identifiers.joined(separator: Self.identifierSeparator)
    }
}
