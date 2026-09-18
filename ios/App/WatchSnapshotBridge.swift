import Foundation
import WatchConnectivity

final class WatchSnapshotBridge: NSObject, WCSessionDelegate {
    static let shared = WatchSnapshotBridge()

    private let contextQueue = DispatchQueue(label: "com.pitchai.codexstatus.watch-context")
    private var pendingSnapshotData: Data?
    private var transferInFlightSnapshotData: Data?

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
            contextQueue.async { [weak self] in
                guard let self else { return }
                pendingSnapshotData = data
                publishPendingContext(to: WCSession.default)
            }
        } catch {
            // The iPhone UI remains authoritative; the Watch will show its prior
            // timestamped snapshot and explicit stale state until the next transfer.
        }
    }

    private func publishPendingContext(to session: WCSession) {
        guard session.activationState == .activated,
              let pendingSnapshotData else { return }
        if transferInFlightSnapshotData != pendingSnapshotData {
            session.transferUserInfo(["snapshot_v1": pendingSnapshotData])
            transferInFlightSnapshotData = pendingSnapshotData
        }
        do {
            try session.updateApplicationContext(["snapshot_v1": pendingSnapshotData])
            self.pendingSnapshotData = nil
        } catch {
            // The queued user-info transfer remains available for background
            // delivery. Preserve the newest snapshot until one delivery path
            // succeeds or the paired-app state changes.
        }
    }

    func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        guard error == nil, activationState == .activated else { return }
        contextQueue.async { [weak self] in
            self?.publishPendingContext(to: session)
        }
    }

    func sessionDidBecomeInactive(_ session: WCSession) {}

    func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    func sessionWatchStateDidChange(_ session: WCSession) {
        contextQueue.async { [weak self] in
            self?.publishPendingContext(to: session)
        }
    }

    func sessionReachabilityDidChange(_ session: WCSession) {
        guard session.isReachable else { return }
        contextQueue.async { [weak self] in
            self?.publishPendingContext(to: session)
        }
    }

    func session(
        _ session: WCSession,
        didFinish userInfoTransfer: WCSessionUserInfoTransfer,
        error: Error?
    ) {
        guard let deliveredData = userInfoTransfer.userInfo["snapshot_v1"] as? Data else {
            return
        }
        contextQueue.async { [weak self] in
            guard let self else { return }
            if transferInFlightSnapshotData == deliveredData {
                transferInFlightSnapshotData = nil
            }
            if error == nil, pendingSnapshotData == deliveredData {
                pendingSnapshotData = nil
            }
        }
    }

    func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        guard let action = message["action"] as? String,
              action == "snapshot" || action == "refresh" else {
            replyHandler(["accepted": false])
            return
        }
        Task { @MainActor in
            if action == "refresh" {
                await SnapshotStore.shared.refresh(manual: true)
            }
            if let snapshot = SnapshotStore.shared.snapshot,
               let data = try? SnapshotCache.encoded(snapshot) {
                replyHandler(["accepted": true, "snapshot_v1": data])
            } else {
                replyHandler(["accepted": false])
            }
        }
    }
}
