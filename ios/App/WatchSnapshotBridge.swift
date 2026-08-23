import Foundation
import WatchConnectivity

final class WatchSnapshotBridge: NSObject, WCSessionDelegate {
    static let shared = WatchSnapshotBridge()

    private override init() {
        super.init()
        guard WCSession.isSupported() else { return }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    func publish(_ snapshot: CodexSnapshot) {
        guard WCSession.isSupported() else { return }
        do {
            let data = try SnapshotCache.encoded(snapshot)
            try WCSession.default.updateApplicationContext(["snapshot_v1": data])
        } catch {
            // The iPhone UI remains authoritative; the Watch will show its prior
            // timestamped snapshot and explicit stale state until the next transfer.
        }
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {}

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        guard message["action"] as? String == "refresh" else {
            replyHandler(["accepted": false])
            return
        }
        Task { @MainActor in
            await SnapshotStore.shared.refresh(manual: true)
            if let snapshot = SnapshotStore.shared.snapshot,
               let data = try? SnapshotCache.encoded(snapshot) {
                replyHandler(["accepted": true, "snapshot_v1": data])
            } else {
                replyHandler(["accepted": false])
            }
        }
    }
}
