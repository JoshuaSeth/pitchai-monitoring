@preconcurrency import BackgroundTasks
import Foundation

internal enum BackgroundRefresh {
    internal static let identifier: String = "com.pitchai.codexstatus.refresh"

    internal static func register() {
        BGTaskScheduler.shared.register(forTaskWithIdentifier: identifier, using: nil) { task in
            guard let refreshTask = task as? BGAppRefreshTask else {
                task.setTaskCompleted(success: false)
                return
            }
            performRefresh(with: refreshTask)
        }
    }

    private static func performRefresh(with task: sending BGAppRefreshTask) {
        Task { @MainActor in
            SnapshotStore.shared.performBackgroundRefresh(task: task)
        }
    }
}
