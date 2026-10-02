import Foundation
import WatchConnectivity

@MainActor
internal final class WatchSnapshotBridge: NSObject, WCSessionDelegate {
    nonisolated private static let snapshotKey: String = "snapshot_v1"

    internal static let shared: WatchSnapshotBridge = .init()

    private var pendingSnapshotData: Data?
    private var transferInFlightSnapshotData: Data?

    override private init() {
        super.init()
        guard WCSession.isSupported() else {
            return
        }
        WCSession.default.delegate = self
        WCSession.default.activate()
    }

    internal func publish(_ snapshot: CodexSnapshot) {
        guard WCSession.isSupported() else {
            return
        }
        do {
            pendingSnapshotData = try SnapshotCache.encoded(snapshot)
            publishPendingContext()
        } catch {
            // The iPhone UI remains authoritative; the Watch keeps its prior
            // timestamped snapshot and explicit stale state until the next transfer.
        }
    }

    nonisolated internal func session(
        _: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        guard error == nil, activationState == .activated else {
            return
        }
        Task { @MainActor [weak self] in
            self?.publishPendingContext()
        }
    }

    nonisolated internal func sessionDidBecomeInactive(_: WCSession) {
        // Pending data is preserved so reactivation can resume delivery.
    }

    nonisolated internal func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }

    nonisolated internal func sessionWatchStateDidChange(_: WCSession) {
        Task { @MainActor [weak self] in
            self?.publishPendingContext()
        }
    }

    nonisolated internal func sessionReachabilityDidChange(_ session: WCSession) {
        guard session.isReachable else {
            return
        }
        Task { @MainActor [weak self] in
            self?.publishPendingContext()
        }
    }

    nonisolated internal func session(
        _: WCSession,
        didFinish userInfoTransfer: WCSessionUserInfoTransfer,
        error: Error?
    ) {
        guard let deliveredData = userInfoTransfer.userInfo[Self.snapshotKey] as? Data else {
            return
        }
        let failed: Bool = error != nil
        Task { @MainActor [weak self] in
            self?.completeTransfer(of: deliveredData, failed: failed)
        }
    }

    nonisolated internal func session(
        _: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: sending @escaping ([String: Any]) -> Void
    ) {
        let action: String? = message["action"] as? String
        guard let action, action == "snapshot" || action == "refresh" else {
            replyHandler(["accepted": false])
            return
        }
        Task { @MainActor in
            if action == "refresh" {
                await SnapshotStore.shared.refresh(manual: true)
            }
            guard let snapshot = SnapshotStore.shared.snapshot else {
                replyHandler(["accepted": false])
                return
            }
            do {
                let data: Data = try SnapshotCache.encoded(snapshot)
                replyHandler(["accepted": true, Self.snapshotKey: data])
            } catch {
                replyHandler(["accepted": false])
            }
        }
    }

    private func completeTransfer(of data: Data, failed: Bool) {
        if transferInFlightSnapshotData == data {
            transferInFlightSnapshotData = nil
        }
        if !failed, pendingSnapshotData == data {
            pendingSnapshotData = nil
        }
    }

    private func publishPendingContext() {
        let session: WCSession = .default
        guard session.activationState == .activated, let pending = pendingSnapshotData else {
            return
        }
        if transferInFlightSnapshotData != pending {
            session.transferUserInfo([Self.snapshotKey: pending])
            transferInFlightSnapshotData = pending
        }
        do {
            try session.updateApplicationContext([Self.snapshotKey: pending])
            pendingSnapshotData = nil
        } catch {
            // The queued user-info transfer remains available for background
            // delivery, so the newest snapshot is preserved until one succeeds.
        }
    }

    deinit {
        // WatchConnectivity owns the session; no other resources are retained here.
    }
}
