// swift-tools-version:5.10
// The Mac app around the web app: a menu bar item that starts the bundled server, shows the app in its own
// window, and keeps itself up to date. Built by ../scripts/build-app.sh, which names it after app.json.
import PackageDescription

let package = Package(
    name: "AppHost",
    platforms: [.macOS("14.0")],
    targets: [
        .executableTarget(name: "AppHost", dependencies: ["UpdateRules"], path: "Sources/AppHost"),
        // The updater's decisions (which version to offer, skipping, going back), with no AppKit, so they can be
        // checked: swift run --package-path mac UpdateChecks
        .target(name: "UpdateRules", path: "Sources/UpdateRules"),
        .executableTarget(name: "UpdateChecks", dependencies: ["UpdateRules"], path: "Checks/UpdateChecks"),
    ]
)
