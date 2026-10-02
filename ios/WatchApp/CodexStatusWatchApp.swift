import SwiftUI

@main
internal struct CodexStatusWatchApp: App {
    @StateObject private var store: WatchSnapshotStore = .init()

    internal var body: some Scene {
        WindowGroup {
            WatchCapacityView()
                .environmentObject(store)
        }
    }
}
