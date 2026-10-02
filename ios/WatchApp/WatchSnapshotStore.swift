import Foundation
import WatchConnectivity
import WidgetKit

@MainActor
internal final class WatchSnapshotStore: NSObject, ObservableObject, WCSessionDelegate {
    private static let requestCooldownSeconds: TimeInterval = 30
    nonisolated private static let snapshotKey: String = "snapshot_v1"

    @Published internal private(set) var snapshot: CodexSnapshot?
    @Published internal private(set) var isRefreshing: Bool = false
    @Published internal private(set) var message: String?

    private let fixtureMode: Bool
    private var lastSnapshotRequestAt: Date?

    override internal init() {
        let arguments: [String] = ProcessInfo.processInfo.arguments
        fixtureMode = arguments.contains("-CodexStatusFixture")
        snapshot = nil
        super.init()
        snapshot = initialSnapshot(arguments: arguments)
        guard !fixtureMode, WCSession.isSupported() else {
            return
        }
        WCSession.default.delegate = self
        WCSession.default.activate()
        apply(context: WCSession.default.receivedApplicationContext)
    }

    nonisolated internal static func snapshotPayload(in context: [String: Any]) -> Data? {
        context[snapshotKey] as? Data
    }

    internal func refresh() {
        if fixtureMode {
            snapshot = .fixture
            message = "Preview refreshed"
            return
        }
        guard WCSession.default.isReachable else {
            message = "Open Codex Status on the paired iPhone to refresh."
            return
        }
        isRefreshing = true
        message = nil
        WCSession.default.sendMessage(
            ["action": "refresh"],
            replyHandler: { [weak self] reply in
                Task { @MainActor in
                    self?.handleRefreshReply(reply)
                }
            },
            errorHandler: { [weak self] _ in
                Task { @MainActor in
                    self?.handleRefreshFailure()
                }
            }
        )
    }

    private func initialSnapshot(arguments: [String]) -> CodexSnapshot? {
        #if DEBUG
            do {
                guard
                    let diagnostic: CodexSnapshot = try SnapshotCache.diagnosticSnapshot(
                        arguments: arguments
                    )
                else {
                    return fixtureMode ? .fixture : SnapshotCache.load()
                }
                try SnapshotCache.save(diagnostic)
                return diagnostic
            } catch {
                preconditionFailure(
                    "Invalid Watch diagnostic snapshot: \(error.localizedDescription)"
                )
            }
        #else
            return fixtureMode ? .fixture : SnapshotCache.load()
        #endif
    }

    private func handleRefreshReply(_ reply: [String: Any]) {
        isRefreshing = false
        guard reply["accepted"] as? Bool == true, let data = Self.snapshotPayload(in: reply) else {
            message = "The iPhone could not complete the refresh."
            return
        }
        apply(snapshotData: data)
        message = "Latest broker state loaded"
    }

    private func handleRefreshFailure() {
        isRefreshing = false
        message = "The paired iPhone is temporarily unreachable."
    }

    internal func requestLatestSnapshot() {
        guard WCSession.default.isReachable else {
            return
        }
        let elapsed: TimeInterval? = lastSnapshotRequestAt.map { requestedAt in
            Date().timeIntervalSince(requestedAt)
        }
        if let elapsed, elapsed < Self.requestCooldownSeconds {
            return
        }
        lastSnapshotRequestAt = Date()
        WCSession.default.sendMessage(
            ["action": "snapshot"],
            replyHandler: { [weak self] reply in
                Task { @MainActor in
                    self?.handleSnapshotReply(reply)
                }
            },
            errorHandler: { [weak self] _ in
                Task { @MainActor in
                    self?.handleSnapshotFailure()
                }
            }
        )
    }

    private func handleSnapshotReply(_ reply: [String: Any]) {
        guard reply["accepted"] as? Bool == true, let data = Self.snapshotPayload(in: reply) else {
            if snapshot == nil {
                message = "The iPhone has not loaded a capacity snapshot yet."
            }
            return
        }
        apply(snapshotData: data)
    }

    private func handleSnapshotFailure() {
        if snapshot == nil {
            message = "Open Codex Status on the paired iPhone to load data."
        }
    }

    internal func apply(context: [String: Any]) {
        apply(snapshotData: Self.snapshotPayload(in: context))
    }

    internal func apply(snapshotData: Data?) {
        guard let snapshotData else {
            return
        }
        do {
            let decoded: CodexSnapshot = try JSONDecoder().decode(
                CodexSnapshot.self,
                from: snapshotData
            )
            try SnapshotCache.save(decoded)
            snapshot = decoded
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            message = "The snapshot sent by the paired iPhone could not be stored."
        }
    }

    internal func reportConnectionFailure() {
        message = "The paired iPhone connection could not start."
    }

    deinit {
        // WatchConnectivity owns the session; no other resources are retained here.
    }
}
