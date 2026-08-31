import SwiftUI

@main
struct CodexStatusApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var store: SnapshotStore

    init() {
        BackgroundRefresh.register()
        _ = WatchSnapshotBridge.shared
        _store = StateObject(wrappedValue: SnapshotStore.shared)
    }

    var body: some Scene {
        WindowGroup {
            CapacityDashboardView()
                .environmentObject(store)
                .task {
                    store.start()
                }
        }
        .onChange(of: scenePhase) { _, phase in
            switch phase {
            case .active:
                store.start()
            case .background:
                store.stopForegroundRefresh()
                store.scheduleBackgroundRefresh()
            case .inactive:
                break
            @unknown default:
                break
            }
        }
    }
}
