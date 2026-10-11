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

/// The menu bar menu. Native features a module needs (hotkeys, recording…) get their items here.
struct MenuContent: View {
    @ObservedObject var host: Host
    @ObservedObject var updater: Updater

    var body: some View {
        Button("Open \(AppConfig.name)") { host.openWindow() }
            .keyboardShortcut("o")
        if let failure = host.failure {
            Text(failure)
        } else if !host.ready {
            Text("Starting…")
        }
        Divider()
        switch updater.state {
        case .available(let version):
            Button("Install Version \(version)…") { updater.install() }
        case .downloading(let version, let progress):
            Text("Downloading \(version)… \(progress.map { "\(Int($0 * 100))%" } ?? "")")
        case .installing(let version):
            Text("Installing \(version)…")
        case .failed(let why):
            Text(why)
            Button("Check for Updates…") { Task { await updater.check(manual: true) } }
        default:
            if Updater.enabled {
                Button(updater.state == .upToDate ? "Up to Date · Check Again" : "Check for Updates…") {
                    Task { await updater.check(manual: true) }
                }
            }
        }
        Toggle("Open at Login", isOn: Binding(get: { host.openAtLogin }, set: { host.setOpenAtLogin($0) }))
        Divider()
        Button("Quit \(AppConfig.name)") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }
}

/// Starts (or finds) the server, then shows the window when it answers.
@MainActor
final class Host: ObservableObject {
    static let shared = Host()

    @Published private(set) var ready = false
    @Published private(set) var failure: String?
    @Published private(set) var openAtLogin = SMAppService.mainApp.status == .enabled

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
