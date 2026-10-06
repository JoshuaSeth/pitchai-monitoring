import Foundation

internal enum BurnFactorPoolChoice: String, CaseIterable {
    case claude = "anthropic"
    case codex = "openai"
    case openCode = "opencode"

    /// Display order on watch faces and in the overview: Codex, Claude, OpenCode.
    internal static var displayOrder: [Self] {
        var order: [Self] = []
        order.append(.codex)
        order.append(.claude)
        order.append(.openCode)
        return order
    }

    internal var kind: String {
        "BurnFactor." + rawValue
    }

    internal var displayName: String {
        switch self {
        case .claude:
            return "Claude"

        case .codex:
            return "Codex"

        case .openCode:
            return "OpenCode"
        }
    }

    /// Three-letter label that fits inside a round complication.
    internal var shortLabel: String {
        switch self {
        case .claude:
            return "CLD"

        case .codex:
            return "CDX"

        case .openCode:
            return "OC"
        }
    }
}
