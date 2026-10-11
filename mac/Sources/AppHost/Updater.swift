import AppKit
import CryptoKit
import Foundation

/// Keeps the app up to date from its GitHub releases (app.json "updateRepo"): checks at launch and every few
/// hours; on request downloads the new disk image, checks it against the SHA-256 published with the release,
/// makes sure the app inside is this app (same bundle ID, intact signature), swaps it in place and relaunches.
///
/// No Apple Developer ID is needed for this: a file the app downloads itself isn't quarantined, so macOS
/// doesn't block the new version. Until the app is signed, though, macOS sees each version as a new app and
/// asks again for any permissions it had (microphone and so on) after an update.
///
/// Updating in the middle of background work is safe: jobs are resumable, so the new version picks them up.
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
        case failed(String)
    }

    @Published private(set) var state: State = .idle
    private var latest: Release?
    private var timer: Timer?
    private(set) var checkedAt: Date?

    struct Release {
        let version: String
        let notes: URL?
        let dmg: URL
        let checksum: URL?
    }

    static let current = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    /// Where releases are looked up: <PREFIX>_UPDATE_URL (tests), else the repo from app.json.
    private static var feed: URL? {
        if let override = AppConfig.env("UPDATE_URL") { return URL(string: override) }
        guard let repo = AppConfig.updateRepo else { return nil }
        return URL(string: "https://api.github.com/repos/\(repo)/releases/latest")
    }

    /// Only a built app updates itself (not a development build).
    static var enabled: Bool { Bundled.isBundled && feed != nil }

    func begin() {
        guard Self.enabled else { return }
        let delay = Double(AppConfig.env("UPDATE_DELAY") ?? "") ?? 20  // tests: shorter
        Task {
            try? await Task.sleep(for: .seconds(delay))  // let the app settle first
            await check()
        }
        timer = Timer.scheduledTimer(withTimeInterval: 6 * 3600, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in await self.check() }
        }
    }

    /// Looks for a new version. `manual`: you asked (Help → Check for Updates…), so show "Checking…" meanwhile.
    func check(manual: Bool = false) async {
        guard let feed = Self.feed else { return }
        if case .downloading = state { return }
        if case .installing = state { return }
        if manual, latest == nil { state = .checking }
        var request = URLRequest(url: feed)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        guard let (data, response) = try? await URLSession.shared.data(for: request),
              (response as? HTTPURLResponse)?.statusCode == 200,
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let tag = json["tag_name"] as? String else {
            if latest == nil, manual || state == .checking { state = .offline }
            return
        }
        checkedAt = Date()
        let version = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        let assets = (json["assets"] as? [[String: Any]]) ?? []
        func asset(_ suffix: String) -> URL? {
            assets.first { ($0["name"] as? String)?.hasSuffix(suffix) == true && ($0["name"] as? String)?.contains(version) == true }
                .flatMap { $0["browser_download_url"] as? String }.flatMap(URL.init(string:))
        }
        guard Self.isNewer(version, than: Self.current), let dmg = asset("-arm64.dmg") else {
            latest = nil
            state = .upToDate
            return
        }
        latest = Release(version: version, notes: (json["html_url"] as? String).flatMap(URL.init(string:)), dmg: dmg,
                         checksum: asset("-arm64.dmg.sha256"))
        state = .available(version)
    }

    static func isNewer(_ a: String, than b: String) -> Bool {
        let x = a.split(separator: ".").map { Int($0) ?? 0 }, y = b.split(separator: ".").map { Int($0) ?? 0 }
        for i in 0..<max(x.count, y.count) {
            let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0
            if p != q { return p > q }
        }
        return false
    }

    // MARK: Installing

    func install() {
        guard let release = latest else { return }
        if case .downloading = state { return }
        if case .installing = state { return }
        let app = Bundle.main.bundleURL
        if app.path.contains("/AppTranslocation/") || !FileManager.default.isWritableFile(atPath: app.deletingLastPathComponent().path) {
            state = .failed("Move \(AppConfig.name) to your Applications folder first; it can't update itself where it is now.")
            return
        }
        state = .downloading(release.version, nil)
        Task {
            do {
                let image = try await download(release)
                state = .installing(release.version)
                let fresh = try await Self.unpack(image, next: app)
                try Self.swap(app, with: fresh)
                Self.relaunch(app)
            } catch {
                state = .failed((error as? UpdateError)?.message ?? error.localizedDescription)
            }
        }
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

    /// Mounts the disk image, checks the app inside, and copies it next to the running one.
    private static func unpack(_ image: URL, next app: URL) async throws -> URL {
        let mount = image.deletingLastPathComponent().appendingPathComponent("mnt")
        try run("/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-noverify", "-mountpoint", mount.path, image.path)
        defer { _ = try? run("/usr/bin/hdiutil", "detach", "-force", mount.path) }
        let inside = mount.appendingPathComponent("\(AppConfig.name).app")
        guard let bundle = Bundle(url: inside), bundle.bundleIdentifier == Bundle.main.bundleIdentifier else {
            throw UpdateError("The update doesn't contain \(AppConfig.name)")
        }
        try run("/usr/bin/codesign", "--verify", "--strict", inside.path)
        let staged = app.deletingLastPathComponent().appendingPathComponent(".\(AppConfig.id)-update.app")
        try? FileManager.default.removeItem(at: staged)
        try run("/usr/bin/ditto", inside.path, staged.path)
        return staged
    }

    private static func swap(_ app: URL, with fresh: URL) throws {
        _ = try FileManager.default.replaceItemAt(app, withItemAt: fresh, backupItemName: nil, options: [])
    }

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
}

struct UpdateError: Error {
    let message: String
    init(_ message: String) { self.message = message }
}
