import XCTest

@MainActor
final class CodexStatusWatchUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    func testDashboardLaunches() {
        let app = XCUIApplication()
        app.launch()

        let title = app.navigationBars["Codex"]
        let titleText = app.staticTexts["Codex"]
        XCTAssertTrue(
            title.waitForExistence(timeout: 45) || titleText.waitForExistence(timeout: 5),
            "The Codex Status root view did not become visible."
        )

        attachScreenshot(named: "watch-dashboard-launch")
    }

    func testLiveSnapshotRenders() {
        let app = XCUIApplication()
        app.launch()

        XCTAssertTrue(
            app.staticTexts["accounts ready"].waitForExistence(timeout: 45),
            "The Watch did not render a live capacity snapshot."
        )
        XCTAssertTrue(
            app.staticTexts["Verified"].exists
                || app.staticTexts["Attention"].exists
                || app.staticTexts["No capacity"].exists
                || app.staticTexts["Stale"].exists,
            "The live snapshot did not expose an explicit broker state."
        )

        attachScreenshot(named: "watch-dashboard-live")
    }

    private func attachScreenshot(named name: String) {
        let attachment = XCTAttachment(screenshot: XCUIScreen.main.screenshot())
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }
}
