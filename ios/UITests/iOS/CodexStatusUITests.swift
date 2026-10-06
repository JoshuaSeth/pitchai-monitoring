import XCTest

@MainActor
internal final class CodexStatusUITests: XCTestCase {
    override internal func setUpWithError() throws {
        continueAfterFailure = false
    }

    override internal func tearDownWithError() throws {
        continueAfterFailure = true
    }

    internal func testPhysicalLiveStatusRenders() {
        let app: XCUIApplication = .init()
        app.launch()

        let hero: XCUIElement = app.descendants(matching: .any).matching(
            NSPredicate(format: "label CONTAINS 'accounts ready'")
        ).firstMatch

        guard hero.waitForExistence(timeout: 60) else {
            XCTFail("physical_ui_stage=live_render classification=\(safeFailure(in: app))")
            return
        }

        guard app.buttons["Refresh broker capacity"].exists else {
            XCTFail("physical_ui_stage=controls classification=refresh_control_missing")
            return
        }

        let attachment: XCTAttachment = .init(screenshot: hero.screenshot())
        attachment.name = "physical-iphone-live-status-hero"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    internal func testFixtureBurnFactorsRender() {
        let app: XCUIApplication = .init()
        app.launchArguments = ["-CodexStatusFixture"]
        app.launch()

        let heading: XCUIElement = app.staticTexts["Burn factor"]
        guard heading.waitForExistence(timeout: 30) else {
            XCTFail("The burn-factor section did not render from the sanitized fixture.")
            return
        }
        let deepSeek: XCUIElement = app.staticTexts["DeepSeek"]
        var swipes: Int = 0
        while !deepSeek.isHittable, swipes < 6 {
            app.swipeUp()
            swipes += 1
        }
        guard deepSeek.isHittable else {
            XCTFail("The DeepSeek burn-factor card was not reachable by scrolling.")
            return
        }

        let attachment: XCTAttachment = .init(screenshot: XCUIScreen.main.screenshot())
        attachment.name = "fixture-iphone-burn-factors"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func safeFailure(in app: XCUIApplication) -> String {
        if app.staticTexts["The capacity service returned an invalid response."].exists {
            return "invalid_server_response"
        }
        if app.staticTexts["The private shared snapshot container is unavailable."].exists {
            return "app_group_unavailable"
        }
        if app.staticTexts[
            "App Attest is unavailable on this device. Live broker data remains locked."
        ].exists {
            return "app_attest_unavailable"
        }
        if app.staticTexts["Live status unavailable"].exists {
            return "live_status_unavailable"
        }
        return "expected_status_view_missing"
    }

    deinit {
        // XCTest owns the runner lifecycle; no additional resources are retained here.
    }
}
