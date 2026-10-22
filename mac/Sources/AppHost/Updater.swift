import AppKit
import CryptoKit
import Foundation
import UpdateRules

/// Keeps the app up to date from its GitHub releases (app.json "updateRepo"): checks at launch and every few
/// hours; on request downloads the new disk image, checks it against the SHA-256 published with the release,
/// makes sure the app inside is this app (same bundle ID, intact signature), swaps it in place and relaunches.
///
/// - **Beta updates** (off unless you turn them on) also offer pre-releases. CI publishes every version as one
///   and promotes it to a full release a few days later (ARCHITECTURE.md §11).
/// - **Go back:** the version an update replaces is kept in the data folder, so the app can return to it with no
///   download, checked the same way (same bundle ID, intact signature). The version you leave is then skipped.
/// - **Skip this version:** it isn't offered again; a newer one is.
/// - **Not while the app is busy** (GET /api/jobs/busy: background work is queued or running). Jobs would pick
///   up again after the restart, but a long one would start over.
///
/// Which version to offer, skipping and going back are decided in UpdateRules, checked by
/// `swift run --package-path mac UpdateChecks`.
///
/// No Apple Developer ID is needed for this: a file the app downloads itself isn't quarantined, so macOS
/// doesn't block the new version. Until the app is signed, though, macOS sees each version as a new app and
/// asks again for any permissions it had (microphone and so on) after an update.
@MainActor
final class Updater: ObservableObject {
    static let shared = Updater()

    enum State: Equatable {
        case idle
        case checking
        case upToDate
        case offline  // couldn't reach GitHub to check
        case available(String)
        case downloading(String, Double?)
        case installing(String)
        case goingBack(String)
        case failed(String)
    }

    @Published private(set) var state: State = .idle {
        didSet { Self.trace("\(state)") }
    }
    @Published private(set) var choices = UpdateChoices.read(try? Data(contentsOf: Updater.choicesFile))
    /// The version Go back returns to, if an update left one here.
    let previous = UpdateRules.goBack(kept: Updater.version(of: Updater.kept), current: Updater.current)
    private var releases: [Release] = []
    private var latest: Release?
    private var lastTry: Attempt?
    private var timer: Timer?
    private(set) var checkedAt: Date?

    private enum Attempt { case install, goBack }

    static let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"

    /// Where releases are looked up: <PREFIX>_UPDATE_URL (tests), else the recent releases of the repo in app.json.
    /// The list rather than GitHub's "latest", which never includes pre-releases.
    private static var feed: URL? {
        if let override = AppConfig.env("UPDATE_URL") { return URL(string: override) }
        guard let repo = AppConfig.updateRepo else { return nil }
        return URL(string: "https://api.github.com/repos/\(repo)/releases?per_page=30")
    }

    /// What updates keep: your choices, and the version the last update replaced. In the data folder, so
    /// <PREFIX>_DATA_DIR moves them too; ".noindex" keeps Spotlight and Launchpad from offering the old copy.
    private static let folder = Bundled.dataDirectory.appendingPathComponent("updates.noindex", isDirectory: true)
    private static let choicesFile = folder.appendingPathComponent("choices.json")
    private static let kept = folder.appendingPathComponent("previous/\(AppConfig.name).app", isDirectory: true)

    /// Only a built app updates itself (not a development build).
    static var enabled: Bool { Bundled.isBundled && feed != nil }

    /// Downloading, installing or going back: nothing else starts meanwhile.
    var working: Bool {
        switch state {
        case .downloading, .installing, .goingBack: true
        default: false
        }
    }

    func begin() {
        guard Self.enabled else { return }
        let delay = Double(AppConfig.env("UPDATE_DELAY") ?? "") ?? 20  // tests: shorter
        Task {
            try? await Task.sleep(for: .seconds(delay))  // let the app settle first
            await check()
            switch Self.testAction {
            case "install": install()
            case "go-back": goBack()
            default: break
            }
        }
        timer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in await self.check() }
        }
    }

    /// Looks for a new version. `manual`: you asked (Check for updates…), so show "Checking…" meanwhile.
    func check(manual: Bool = false) async {
        guard let feed = Self.feed, !working else { return }
        if manual, latest == nil { state = .checking }
        var request = URLRequest(url: feed)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) else {
            if latest == nil, manual || state == .checking { state = .offline }
            return
        }
        releases = UpdateRules.releases(from: json)
        checkedAt = Date()
        refresh()
    }

    /// Works out what to offer from the releases last seen, after a check or when a choice changes.
    private func refresh() {
        guard checkedAt != nil, !working else { return }
        latest = UpdateRules.offer(releases, current: Self.current, beta: choices.beta, skipped: choices.skipped)
        state = latest.map { .available($0.version) } ?? .upToDate
    }

    // MARK: Your choices

    var beta: Bool {
        get { choices.beta }
        set {
            save { $0.beta = newValue }
            Task { await check() }  // a fresh look, since betas come out more often
        }
    }

    /// A version you skipped or went back from, while it's still ahead of this one.
    var skipped: String? { UpdateRules.stillSkipped(choices.skipped, current: Self.current) }

    func skip() {
        guard let latest, !working else { return }
        save { $0.skipped = latest.version }
    }

    func unskip() { save { $0.skipped = nil } }

    private func save(_ change: (inout UpdateChoices) -> Void) {
        change(&choices)
        try? FileManager.default.createDirectory(at: Self.folder, withIntermediateDirectories: true,
                                                 attributes: [.posixPermissions: 0o700])
        try? choices.data().write(to: Self.choicesFile, options: .atomic)
        refresh()
    }

    // MARK: Installing

    /// Installs the version on offer. The one it replaces is kept for Go back.
    func install() {
        guard let release = latest, !working else { return }
        lastTry = .install
        state = .downloading(release.version, nil)
        Task {
            do {
                let app = try await Self.preflight("update")
                let image = try await download(release)
                state = .installing(release.version)
                let fresh = try await Self.unpack(image, next: app)
                try await Self.untilIdle("update", patience: 60)
                try Self.swap(app, with: fresh, keepingOld: true)
                Self.relaunch(app)
            } catch {
                state = .failed((error as? UpdateError)?.message ?? error.localizedDescription)
            }
        }
    }

    /// Returns to the version the last update replaced, kept on this Mac, and skips this one until a newer
    /// version comes out. The data stays: migrations only add, so the older version opens it too.
    func goBack() {
        guard !working else { return }
        guard let version = previous else {
            state = .failed("There’s no earlier version on this Mac to go back to.")
            return
        }
        lastTry = .goBack
        state = .goingBack(version)
        Task {
            do {
                let app = try await Self.preflight("go back")
                let old = try Self.stage(Self.kept, next: app, missing: "The version kept for going back isn’t \(AppConfig.name)")
                try await Self.untilIdle("go back", patience: 60)
                try Self.swap(app, with: old, keepingOld: false)
                try? FileManager.default.removeItem(at: Self.kept)
                save { $0.skipped = Self.current }  // don't offer the version you left; a newer one, yes
                Self.relaunch(app)
            } catch {
                state = .failed((error as? UpdateError)?.message ?? error.localizedDescription)
            }
        }
    }

    /// Everything Settings → Updates shows, for the page in the app's window (MainWindow sends it on each change).
    var report: [String: Any] {
        var out: [String: Any] = ["enabled": Self.enabled, "current": Self.current, "beta": beta, "working": working]
        switch state {
        case .idle: out["state"] = "idle"
        case .checking: out["state"] = "checking"
        case .upToDate: out["state"] = "up-to-date"
        case .offline: out["state"] = "offline"
        case .available(let v): out["state"] = "available"; out["version"] = v
        case .downloading(let v, let p): out["state"] = "downloading"; out["version"] = v; out["progress"] = p
        case .installing(let v): out["state"] = "installing"; out["version"] = v
        case .goingBack(let v): out["state"] = "going-back"; out["version"] = v
        case .failed(let why): out["state"] = "failed"; out["error"] = why
        }
        if let latest, case .available = state { out["prerelease"] = latest.prerelease }
        out["skipped"] = skipped
        out["previous"] = previous
        out["checked_at"] = checkedAt.map { ISO8601DateFormatter().string(from: $0) }
        return out
    }

    /// After a failure: whatever failed, again (or a fresh check).
    func tryAgain() {
        switch lastTry {
        case .goBack: goBack()
        case .install where latest != nil: install()
        default: Task { await check(manual: true) }
        }
    }

    /// The app can be replaced: it's somewhere it can write, and it isn't in the middle of something.
    private static func preflight(_ doing: String) async throws -> URL {
        let app = Bundle.main.bundleURL
        if app.path.contains("/AppTranslocation/") || !FileManager.default.isWritableFile(atPath: app.deletingLastPathComponent().path) {
            throw UpdateError("Move \(AppConfig.name) to your Applications folder first; it can’t \(doing) where it is now.")
        }
        try await untilIdle(doing, patience: 0)
        return app
    }

    /// Waits up to `patience` seconds for the app's background work to finish, then gives up.
    private static func untilIdle(_ doing: String, patience: Double) async throws {
        let deadline = Date().addingTimeInterval(patience)
        while await serverBusy() {
            guard Date() < deadline else {
                throw UpdateError("\(AppConfig.name) is in the middle of something, so it didn’t \(doing). Try again when it’s done.")
            }
            try? await Task.sleep(for: .seconds(1))
        }
    }

    private static func serverBusy() async -> Bool {
        var request = URLRequest(url: AppConfig.serverURL.appendingPathComponent("api/jobs/busy"))
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalCacheData
        guard let (data, response) = try? await URLSession.shared.data(for: request) else { return false }
        return UpdateRules.busy(status: (response as? HTTPURLResponse)?.statusCode ?? 0, body: data)
    }

    private func download(_ release: Release) async throws -> URL {
        let folder = FileManager.default.temporaryDirectory.appendingPathComponent("\(AppConfig.id)-update-\(UUID().uuidString)")
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        let target = folder.appendingPathComponent("update.dmg")

        // A plain download task (fast, straight to disk); its progress is shown while it runs.
        let downloaded: URL = try await withCheckedThrowingContinuation { done in
            let task = URLSession.shared.downloadTask(with: release.dmg) { file, response, error in
                if let error { return done.resume(throwing: error) }
                guard let file, (response as? HTTPURLResponse)?.statusCode == 200 else {
                    return done.resume(throwing: UpdateError("Couldn't download the update"))
                }
                do {
                    try FileManager.default.moveItem(at: file, to: target)  // the temporary file goes away after this callback
                    done.resume(returning: target)
                } catch {
                    done.resume(throwing: error)
                }
            }
            let progress = task.progress
            Task { @MainActor [weak self] in
                while !progress.isFinished, !progress.isCancelled {
                    if progress.totalUnitCount > 0 { self?.state = .downloading(release.version, progress.fractionCompleted) }
                    try? await Task.sleep(for: .milliseconds(300))
                }
            }
            task.resume()
        }

        guard let checksumURL = release.checksum,
              let (sumData, _) = try? await URLSession.shared.data(from: checksumURL),
              let published = String(data: sumData, encoding: .utf8)?.split(separator: " ").first.map(String.init)?.lowercased()
        else { throw UpdateError("The update has no published checksum, so it wasn't installed") }
        guard try Self.sha256(of: downloaded) == published else {
            throw UpdateError("The update didn't match its published checksum, so it wasn't installed")
        }
        return downloaded
    }

    private static func sha256(of file: URL) throws -> String {
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        while let chunk = try handle.read(upToCount: 4 << 20), !chunk.isEmpty {
            hasher.update(data: chunk)
        }
        return hasher.finalize().map { String(format: "%02x", $0) }.joined()
    }

    /// Mounts the disk image and stages the app inside it next to the running one.
    private static func unpack(_ image: URL, next app: URL) async throws -> URL {
        let mount = image.deletingLastPathComponent().appendingPathComponent("mnt")
        try run("/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-noverify", "-mountpoint", mount.path, image.path)
        defer { _ = try? run("/usr/bin/hdiutil", "detach", "-force", mount.path) }
        return try stage(mount.appendingPathComponent("\(AppConfig.name).app"), next: app,
                         missing: "The update doesn't contain \(AppConfig.name)")
    }

    /// Copies an app next to the running one, once it's sure it's this app (same bundle ID) with an intact
    /// signature. The same check for a download and for the kept version.
    private static func stage(_ source: URL, next app: URL, missing: String) throws -> URL {
        guard info(of: source)["CFBundleIdentifier"] as? String == Bundle.main.bundleIdentifier else {
            throw UpdateError(missing)
        }
        let staged = app.deletingLastPathComponent().appendingPathComponent(".\(AppConfig.id)-update.app")
        try? FileManager.default.removeItem(at: staged)
        try run("/usr/bin/ditto", source.path, staged.path)
        do {
            try run("/usr/bin/codesign", "--verify", "--strict", staged.path)
        } catch {
            try? FileManager.default.removeItem(at: staged)
            throw error
        }
        return staged
    }

    /// Puts `fresh` in the app's place. `keepingOld`: the version it replaces moves to the data folder, for Go
    /// back. Keeping it is a nicety; if it can't be kept, the update still goes ahead.
    private static func swap(_ app: URL, with fresh: URL, keepingOld: Bool) throws {
        let files = FileManager.default
        guard keepingOld else {
            _ = try files.replaceItemAt(app, withItemAt: fresh, backupItemName: nil, options: [])
            return
        }
        let backupName = ".\(AppConfig.id)-previous.app"
        let old = app.deletingLastPathComponent().appendingPathComponent(backupName)
        try? files.removeItem(at: old)
        _ = try files.replaceItemAt(app, withItemAt: fresh, backupItemName: backupName, options: [.withoutDeletingBackupItem])
        do {
            try files.createDirectory(at: kept.deletingLastPathComponent(), withIntermediateDirectories: true,
                                      attributes: [.posixPermissions: 0o700])
            try? files.removeItem(at: kept)
            try files.moveItem(at: old, to: kept)
        } catch {
            try? files.removeItem(at: old)
        }
    }

    /// An app's Info.plist, read afresh (Bundle caches what it read from a path, and these paths get reused).
    private static func info(of app: URL) -> [String: Any] {
        guard let data = try? Data(contentsOf: app.appendingPathComponent("Contents/Info.plist")),
              let plist = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any] else { return [:] }
        return plist
    }

    private static func version(of app: URL) -> String? { info(of: app)["CFBundleShortVersionString"] as? String }

    /// Opens the new version once this one has quit (and stopped its server).
    private static func relaunch(_ app: URL) {
        if AppConfig.env("UPDATE_NO_RELAUNCH") != nil {  // tests: just quit
            NSApp.terminate(nil)
            return
        }
        let pid = ProcessInfo.processInfo.processIdentifier
        let script = "while kill -0 \(pid) 2>/dev/null; do sleep 0.2; done; /usr/bin/open \"\(app.path)\""
        let opener = Process()
        opener.executableURL = URL(fileURLWithPath: "/bin/sh")
        opener.arguments = ["-c", script]
        try? opener.run()
        NSApp.terminate(nil)
    }

    @discardableResult
    private static func run(_ tool: String, _ args: String...) throws -> String {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: tool)
        process.arguments = args
        let out = Pipe()
        process.standardOutput = out
        process.standardError = out
        try process.run()
        process.waitUntilExit()
        let text = String(data: out.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        guard process.terminationStatus == 0 else {
            throw UpdateError("Updating failed at \((tool as NSString).lastPathComponent): \(text.prefix(200))")
        }
        return text
    }

    // MARK: Tests

    /// scripts/smoke-test.sh: <PREFIX>_UPDATE_TEST=install or go-back does that after the first check, and
    /// every state is written to stderr as "update: <state>".
    private static let testAction = AppConfig.env("UPDATE_TEST")

    private static func trace(_ text: String) {
        guard testAction != nil else { return }
        FileHandle.standardError.write(Data("update: \(text)\n".utf8))
    }
}

struct UpdateError: Error {
    let message: String
    init(_ message: String) { self.message = message }
}
