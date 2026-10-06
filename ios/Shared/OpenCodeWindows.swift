import Foundation

/// The rolling 5-hour, weekly and monthly OpenCode Go windows in the Codex window shape.
internal struct OpenCodeWindows: Codable, Equatable, Sendable {
    internal let rolling: UsageWindow?
    internal let weekly: UsageWindow?
    internal let monthly: UsageWindow?
}
