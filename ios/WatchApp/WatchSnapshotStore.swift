import Foundation
import WatchConnectivity
import WidgetKit

@MainActor
final class WatchSnapshotStore: NSObject, ObservableObject, WCSessionDelegate {
    @Published private(set) var snapshot: CodexSnapshot?
    @Published private(set) var isRefreshing = false
    @Published private(set) var message: String?

    private let fixtureMode: Bool
    private var lastSnapshotRequestAt: Date?

    override init() {
        fixtureMode = ProcessInfo.processInfo.arguments.contains("-CodexStatusFixture")
        snapshot = fixtureMode ? .fixture : SnapshotCache.load()
        super.init()
        guard !fixtureMode, WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
        apply(context: WCSession.default.receivedApplicationContext)
    }

    func refresh() {
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
                    self?.isRefreshing = false
                    guard reply["accepted"] as? Bool == true,
                          let data = reply["snapshot_v1"] as? Data else {
                        self?.message = "The iPhone could not complete the refresh."
                        return
                    }
                    self?.apply(snapshotData: data)
                    self?.message = "Latest broker state loaded"
                }
            },
            errorHandler: { [weak self] _ in
                Task { @MainActor in
                    self?.isRefreshing = false
                    self?.message = "The paired iPhone is temporarily unreachable."
                }
            }
        )
    }

    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        if error != nil {
            Task { @MainActor [weak self] in
                self?.message = "The paired iPhone connection could not start."
            }
            return
        }
        let context = session.receivedApplicationContext
        Task { @MainActor [weak self] in
            self?.apply(context: context)
            self?.requestLatestSnapshot()
        }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        guard session.isReachable else { return }
        Task { @MainActor [weak self] in
            self?.requestLatestSnapshot()
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveApplicationContext applicationContext: [String: Any]
    ) {
        Task { @MainActor [weak self] in
            self?.apply(context: applicationContext)
        }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveUserInfo userInfo: [String: Any] = [:]
    ) {
        Task { @MainActor [weak self] in
            self?.apply(context: userInfo)
        }
    }

    private func requestLatestSnapshot() {
        guard WCSession.default.isReachable else { return }
        if let lastSnapshotRequestAt,
           Date().timeIntervalSince(lastSnapshotRequestAt) < 30 {
            return
        }
        lastSnapshotRequestAt = Date()
        WCSession.default.sendMessage(
            ["action": "snapshot"],
            replyHandler: { [weak self] reply in
                Task { @MainActor in
                    guard reply["accepted"] as? Bool == true,
                          let data = reply["snapshot_v1"] as? Data else {
                        if self?.snapshot == nil {
                            self?.message = "The iPhone has not loaded a capacity snapshot yet."
                        }
                        return
                    }
                    self?.apply(snapshotData: data)
                }
            },
            errorHandler: { [weak self] _ in
                Task { @MainActor in
                    if self?.snapshot == nil {
                        self?.message = "Open Codex Status on the paired iPhone to load data."
                    }
                }
            }
        )
    }

    private func apply(context: [String: Any]) {
        guard let data = context["snapshot_v1"] as? Data else { return }
        apply(snapshotData: data)
    }

    private func apply(snapshotData: Data) {
        guard let decoded = try? JSONDecoder().decode(CodexSnapshot.self, from: snapshotData) else {
            message = "The iPhone sent an invalid snapshot."
            return
        }
        do {
            try SnapshotCache.save(decoded)
            snapshot = decoded
            WidgetCenter.shared.reloadAllTimelines()
        } catch {
            message = "The private Watch cache is unavailable."
        }
    }
}
