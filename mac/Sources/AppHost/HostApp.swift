import AppKit
import ServiceManagement
import SwiftUI

@main
enum Entry {
    @MainActor
    static func main() {
        HostApp.main()
    }
}

final class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)  // menu bar only until the window opens
        // Opened by you (not by "Open at Login"): show the window, since a menu bar icon alone looks like nothing happened.
        let event = NSAppleEventManager.shared().currentAppleEvent
        let atLogin = event?.paramDescriptor(forKeyword: keyAEPropData)?.enumCodeValue == keyAELaunchedAsLogInItem
        MainActor.assumeIsolated {
            Host.shared.begin(openWindow: !atLogin)
            Updater.shared.begin()
        }
    }

    /// Double-clicking the app again (or opening it from Spotlight) brings up the window.
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        MainActor.assumeIsolated { Host.shared.openWindow() }
        return true
    }

    func applicationWillTerminate(_ notification: Notification) {
        MainActor.assumeIsolated { BundledServer.shared.stop() }
    }
}

struct HostApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var host = Host.shared
    @StateObject private var updater = Updater.shared

    var body: some Scene {
        MenuBarExtra {
            MenuContent(host: host, updater: updater)
        } label: {
            Image(nsImage: host.ready ? Mark.menuIcon : Mark.menuIconDimmed)
        }
    }
}

/// The menu bar menu: the app, then the sidebar's sections (each enabled module's nav, from the page).
/// Native features a module needs (hotkeys, recording…) get their items here.
struct MenuContent: View {
    @ObservedObject var host: Host
    @ObservedObject var updater: Updater

    var body: some View {
        Button("Open \(AppConfig.name)") { host.openWindow() }
            .keyboardShortcut("o")
        ForEach(host.sections, id: \.self) { section in
            Button(section.label) { host.openWindow(page: section.path) }
                .disabled(!host.ready)
        }
        if let failure = host.failure {
            Text(failure)
        } else if !host.ready {
            Text("Starting…")
        }
        Divider()
        if Updater.enabled {
            UpdateItems(updater: updater)
        }
        Toggle("Open at login", isOn: Binding(get: { host.openAtLogin }, set: { host.setOpenAtLogin($0) }))
        Divider()
        Button("Show data folder") { NSWorkspace.shared.activateFileViewerSelecting([Bundled.dataDirectory]) }
        Button("Show server log") { NSWorkspace.shared.open(Bundled.logFile) }
        Divider()
        Button("Quit \(AppConfig.name)") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}

/// What's on offer, then "Updates" with the rest: beta updates, a skipped version, and going back.
struct UpdateItems: View {
    @ObservedObject var updater: Updater

    var body: some View {
        switch updater.state {
        case .available(let version):
            Button("Install version \(version)…") { updater.install() }
            Button("Skip this version") { updater.skip() }
        case .downloading(let version, let progress):
            Text("Downloading \(version)…\(progress.map { " \(Int($0 * 100))%" } ?? "")")
        case .installing(let version):
            Text("Installing \(version)…")
        case .goingBack(let version):
            Text("Going back to \(version)…")
        case .failed(let why):
            Text(why)
            Button("Try again") { updater.tryAgain() }
        case .checking:
            Text("Checking for updates…")
        case .offline:
            Button("Couldn’t reach GitHub · Try again") { Task { await updater.check(manual: true) } }
        case .lockedDown:
            Button("Lockdown is on · Check again") { Task { await updater.check(manual: true) } }
        case .upToDate:
            Button("Up to date · Check again") { Task { await updater.check(manual: true) } }
        case .idle:
            Button("Check for updates…") { Task { await updater.check(manual: true) } }
        }
        Menu("Updates") {
            Toggle("Beta updates", isOn: Binding(get: { updater.beta }, set: { updater.beta = $0 }))
            if let skipped = updater.skipped {
                Button("Offer \(skipped) again") { updater.unskip() }
            }
            if let previous = updater.previous {
                Divider()
                Button("Go back to \(previous)…") { Self.confirmGoBack(to: previous, updater: updater) }
            }
        }
        .disabled(updater.working)
    }

    /// Going back replaces the app and restarts it, so it asks first.
    static func confirmGoBack(to previous: String, updater: Updater) {
        let name = AppConfig.name, current = Updater.current
        NSApp.activate()
        let alert = NSAlert()
        alert.messageText = "Go back to \(name) \(previous)?"
        alert.informativeText = "\(name) \(current) is replaced with \(previous), the version it updated from, and restarts. "
            + "Your data stays. \(current) won’t be offered again; the next version will."
        alert.addButton(withTitle: "Go back to \(previous)")
        alert.addButton(withTitle: "Cancel")
        if alert.runModal() == .alertFirstButtonReturn { updater.goBack() }
    }
}

/// A section of the app as the menu lists it: a module's nav item from the sidebar, without its icon.
struct NavItem: Codable, Hashable {
    let label: String
    let path: String  // a route without "#/", e.g. "inbox"
}

/// Starts (or finds) the server, then shows the window when it answers.
@MainActor
final class Host: ObservableObject {
    static let shared = Host()
    private static let sectionsKey = "menuSections"

    @Published private(set) var ready = false
    @Published private(set) var failure: String?
    @Published private(set) var openAtLogin = SMAppService.mainApp.status == .enabled
    /// The sidebar's sections, which the page sends whenever it loads. Kept, so the menu has them on a launch
    /// that opens no window (at login); a module turned on or off shows up the next time the window opens.
    @Published private(set) var sections: [NavItem] = UserDefaults.standard.data(forKey: Host.sectionsKey)
        .flatMap { try? JSONDecoder().decode([NavItem].self, from: $0) } ?? []

    func setSections(fromJSON data: Data) {
        guard let sent = try? JSONDecoder().decode([NavItem].self, from: data) else { return }
        let usable = Array(sent.filter { !$0.label.isEmpty && !$0.path.isEmpty }.prefix(20))
        guard usable != sections else { return }
        sections = usable
        UserDefaults.standard.set(try? JSONEncoder().encode(usable), forKey: Self.sectionsKey)
    }

    func begin(openWindow: Bool) {
        Task {
            if Bundled.isBundled, !(await Self.answering()) {
                do {
                    try BundledServer.shared.start(port: AppConfig.port)
                } catch {
                    failure = "\(AppConfig.name) couldn't start its server: \(error.localizedDescription)"
                    return
                }
            }
            let deadline = Date().addingTimeInterval(40)  // first launch compiles nothing, but a slow disk can take a while
            while !(await Self.answering()), Date() < deadline, BundledServer.shared.failure == nil {
                try? await Task.sleep(for: .milliseconds(250))
            }
            ready = await Self.answering()
            if !ready, failure == nil {
                failure = BundledServer.shared.failure ?? "The server didn't start. Log: \(Bundled.logFile.path)"
            }
            if ready, openWindow { self.openWindow() }
            if ready { watch() }
        }
    }

    /// A second copy of the app uses the first one's server rather than fighting it for the port, and that server
    /// stops when the first copy quits. So keep an eye on it: when nothing answers any more, start this copy's
    /// own server and reload the window.
    private func watch() {
        guard Bundled.isBundled else { return }
        Task {
            while true {
                try? await Task.sleep(for: .seconds(3))
                let server = BundledServer.shared
                if server.isRunning || server.isStopping || server.failure != nil { continue }
                if await Self.answering() { continue }
                do { try server.start(port: AppConfig.port) } catch { continue }
                let deadline = Date().addingTimeInterval(40)
                while !(await Self.answering()), Date() < deadline, server.failure == nil {
                    try? await Task.sleep(for: .milliseconds(250))
                }
                ready = await Self.answering()
                if ready { MainWindow.shared.reload() } else { serverFailed() }
            }
        }
    }

    func serverFailed() {
        ready = false
        failure = BundledServer.shared.failure
    }

    func openWindow(page: String? = nil) {
        var url = AppConfig.serverURL
        if let page { url = URL(string: "#/\(page)", relativeTo: url)?.absoluteURL ?? url }
        if AppConfig.env("NO_OPEN") != nil {  // tests: say what would open instead of opening it
            FileHandle.standardError.write(Data("Would open \(url.absoluteString)\n".utf8))
            return
        }
        MainWindow.shared.show(url)
    }

    func setOpenAtLogin(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            NSSound.beep()
        }
        openAtLogin = SMAppService.mainApp.status == .enabled
    }

    /// True when *this* app's server answers on the port (not another family app that happens to use it).
    static func answering() async -> Bool {
        var request = URLRequest(url: AppConfig.serverURL.appendingPathComponent("api/app"))
        request.timeoutInterval = 2
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return false }
        return json["id"] as? String == AppConfig.id
    }
}
