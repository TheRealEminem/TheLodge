import Foundation

/// Who this app is. build-app.sh copies it from app.json into Info.plist; a development build (swift run)
/// falls back to the defaults below and to the environment.
enum AppConfig {
    private static let info = Bundle.main.infoDictionary ?? [:]
    private static let environment = ProcessInfo.processInfo.environment

    static let name = info["CFBundleDisplayName"] as? String ?? "Starter"
    static let id = info["FamilyAppID"] as? String ?? "starter"
    static let envPrefix = info["FamilyEnvPrefix"] as? String ?? "STARTER"
    static let port = Int(info["FamilyPort"] as? String ?? "") ?? 8790
    static let updateRepo = (info["FamilyUpdateRepo"] as? String).flatMap { $0.isEmpty ? nil : $0 }

    static func env(_ key: String) -> String? { environment["\(envPrefix)_\(key)"] }

    /// <PREFIX>_SERVER_URL points the window at another server (development, or a server install).
    static let serverURL = env("SERVER_URL").flatMap(URL.init(string:)) ?? URL(string: "http://127.0.0.1:\(port)")!
}

/// Where things live inside the .app. A development build has nothing inside, so `isBundled` is false.
enum Bundled {
    static let resources = Bundle.main.resourceURL
    static let python = resources?.appendingPathComponent("python/bin/python3")
    static let isBundled = python.map { FileManager.default.isExecutableFile(atPath: $0.path) } ?? false

    /// Everything the app keeps. Survives updating or deleting the app. <PREFIX>_DATA_DIR overrides it.
    static let dataDirectory = AppConfig.env("DATA_DIR").map { URL(fileURLWithPath: $0, isDirectory: true) }
        ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(AppConfig.name, isDirectory: true)
    static let logFile = dataDirectory.appendingPathComponent("logs/server.log")
}
