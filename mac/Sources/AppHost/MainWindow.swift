import AppKit
import Combine
import WebKit

/// The app's own window: the web app in a WebKit view, so no browser is involved. While it's open the app has
/// a Dock icon and a menu bar (Edit for copy and paste, View → Reload); closing it leaves the menu bar item.
/// Links to other sites open in your browser.
///
/// The page talks to this window through window.webkit.messageHandlers.app (see core/web/api.ts):
///   "quit"            quit the app
///   "reveal:<path>"   show a file or folder in Finder
///   "menu:<json>"     the sidebar's sections, [{"label", "path"}], for the menu bar menu
///   "updates:<what>"  Settings → Updates: get, check, install, skip, unskip, beta-on, beta-off, go-back, try-again.
///                     The window answers each, and every change after, with an "app-updates" event on the page
///                     whose detail is Updater.report.
/// and asks your Mac's Calendar through window.webkit.messageHandlers.calendar, which answers (CalendarBridge.swift).
@MainActor
final class MainWindow: NSObject, NSWindowDelegate, WKUIDelegate, WKNavigationDelegate, WKScriptMessageHandler {
    static let shared = MainWindow()

    private var window: NSWindow?
    private var webView: WKWebView?
    private var updatesWatch: AnyCancellable?

    func show(_ url: URL) {
        let web = webView ?? build()
        if let current = web.url, current.host == url.host, current.port == url.port {
            if let fragment = url.fragment { web.evaluateJavaScript("location.hash = \(Self.jsString("#" + fragment))") }
        } else {
            // Always fetch the page afresh: WebKit keeps its cache across launches, and after an update it would
            // otherwise show the old version's page and scripts.
            web.load(URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData))
        }
        if NSApp.activationPolicy() != .regular {
            NSApp.setActivationPolicy(.regular)
            NSApp.mainMenu = Self.menu()
        }
        NSApp.activate(ignoringOtherApps: true)
        window?.makeKeyAndOrderFront(nil)
    }

    private func build() -> WKWebView {
        let config = WKWebViewConfiguration()
        let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "dev"
        config.applicationNameForUserAgent = "\(AppConfig.name.replacingOccurrences(of: " ", with: ""))App/\(version)"
        config.userContentController.add(self, name: "app")
        config.userContentController.addScriptMessageHandler(CalendarBridge.shared, contentWorld: .page, name: "calendar")
        // objectWillChange fires before the change, so the report is read on the next turn of the main loop.
        updatesWatch = Updater.shared.objectWillChange.sink { [weak self] _ in
            Task { @MainActor in self?.sendUpdates() }
        }

        let web = WKWebView(frame: NSRect(x: 0, y: 0, width: 1280, height: 860), configuration: config)
        web.uiDelegate = self
        web.navigationDelegate = self
        web.allowsBackForwardNavigationGestures = false
        web.setValue(false, forKey: "drawsBackground")  // no white flash before the page paints

        let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 1280, height: 860),
                              styleMask: [.titled, .closable, .miniaturizable, .resizable], backing: .buffered, defer: false)
        window.title = AppConfig.name
        window.minSize = NSSize(width: 420, height: 560)
        window.isReleasedWhenClosed = false
        window.delegate = self
        window.contentView = web
        window.center()
        window.setFrameAutosaveName("\(AppConfig.id)MainWindow")
        window.tabbingMode = .disallowed
        self.window = window
        webView = web
        return web
    }

    func windowWillClose(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)  // back to living in the menu bar
    }

    @objc func reload() { webView?.reload() }
    @objc func openSettings() { Host.shared.openWindow(page: "settings") }

    // MARK: Messages from the page

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard let body = message.body as? String else { return }
        if body == "quit" { NSApp.terminate(nil) }
        if body.hasPrefix("reveal:") {
            let url = URL(fileURLWithPath: String(body.dropFirst("reveal:".count)))
            if FileManager.default.fileExists(atPath: url.path) { NSWorkspace.shared.activateFileViewerSelecting([url]) }
        }
        if body.hasPrefix("menu:") { Host.shared.setSections(fromJSON: Data(body.dropFirst("menu:".count).utf8)) }
        if body.hasPrefix("updates:") { updates(String(body.dropFirst("updates:".count))) }
    }

    private func updates(_ what: String) {
        let updater = Updater.shared
        switch what {
        case "check": Task { await updater.check(manual: true) }
        case "install": updater.install()
        case "skip": updater.skip()
        case "unskip": updater.unskip()
        case "beta-on": updater.beta = true
        case "beta-off": updater.beta = false
        case "go-back": if let previous = updater.previous { UpdateItems.confirmGoBack(to: previous, updater: updater) }
        case "try-again": updater.tryAgain()
        default: break
        }
        sendUpdates()
    }

    /// Tells the page where updates stand (Settings → Updates listens for it).
    private func sendUpdates() {
        guard let webView, let data = try? JSONSerialization.data(withJSONObject: Updater.shared.report),
              let json = String(data: data, encoding: .utf8) else { return }
        webView.evaluateJavaScript("window.dispatchEvent(new CustomEvent('app-updates', { detail: \(json) }))")
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) { sendUpdates() }

    /// File and folder pickers on the page (<input type="file">).
    func webView(_ webView: WKWebView, runOpenPanelWith parameters: WKOpenPanelParameters, initiatedByFrame frame: WKFrameInfo,
                 completionHandler: @escaping @MainActor ([URL]?) -> Void) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = parameters.allowsDirectories
        panel.canChooseFiles = !parameters.allowsDirectories
        panel.allowsMultipleSelection = parameters.allowsMultipleSelection
        if let window { panel.beginSheetModal(for: window) { completionHandler($0 == .OK ? panel.urls : nil) } }
        else { panel.begin { completionHandler($0 == .OK ? panel.urls : nil) } }
    }

    // MARK: Links and pop-ups

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction, decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void) {
        if let url = action.request.url, action.navigationType == .linkActivated, !isOurs(url) {
            NSWorkspace.shared.open(url)
            return decisionHandler(.cancel)
        }
        decisionHandler(.allow)
    }

    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration, for action: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if let url = action.request.url { NSWorkspace.shared.open(url) }
        return nil
    }

    private func isOurs(_ url: URL?) -> Bool {
        guard let url else { return false }
        let current = webView?.url ?? AppConfig.serverURL
        return url.host == current.host && url.port == current.port
    }

    private static func jsString(_ text: String) -> String {
        let data = try? JSONSerialization.data(withJSONObject: [text])
        return String(data: data ?? Data("[\"\"]".utf8), encoding: .utf8).map { String($0.dropFirst().dropLast()) } ?? "\"\""
    }

    // MARK: Menu

    private static func menu() -> NSMenu {
        let main = NSMenu()
        func submenu(_ title: String, _ items: [NSMenuItem]) -> NSMenu {
            let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            holder.submenu = menu
            main.addItem(holder)
            return menu
        }
        func item(_ title: String, _ action: Selector?, _ key: String, _ modifiers: NSEvent.ModifierFlags = .command, target: AnyObject? = nil) -> NSMenuItem {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.keyEquivalentModifierMask = modifiers
            item.target = target
            return item
        }
        let name = AppConfig.name
        _ = submenu(name, [
            item("About \(name)", #selector(NSApplication.orderFrontStandardAboutPanel(_:)), ""),
            .separator(),
            item("Settings…", #selector(MainWindow.openSettings), ",", target: MainWindow.shared),
            .separator(),
            item("Hide \(name)", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            .separator(),
            item("Quit \(name)", #selector(NSApplication.terminate(_:)), "q"),
        ])
        _ = submenu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        _ = submenu("View", [
            item("Reload", #selector(MainWindow.reload), "r", target: MainWindow.shared),
        ])
        let window = submenu("Window", [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ])
        NSApp.windowsMenu = window
        return main
    }
}
