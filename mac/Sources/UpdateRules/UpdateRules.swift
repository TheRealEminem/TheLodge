import Foundation

/// The updater's decisions, kept apart from AppKit and the network so they can be checked on their own:
///   swift run --package-path mac UpdateChecks
/// A release counts when it has this Mac's disk image, "<Name>-<version>-arm64.dmg", with its ".sha256" beside it
/// (scripts/build-app.sh --dmg makes both).
public struct Release: Equatable, Sendable {
    public let version: String
    public let prerelease: Bool
    public let notes: URL?
    public let dmg: URL
    public let checksum: URL?

    public init(version: String, prerelease: Bool, notes: URL?, dmg: URL, checksum: URL?) {
        self.version = version
        self.prerelease = prerelease
        self.notes = notes
        self.dmg = dmg
        self.checksum = checksum
    }
}

/// What you chose about updates, kept in the data folder (updates.noindex/choices.json).
public struct UpdateChoices: Codable, Equatable, Sendable {
    /// Beta updates: also offer pre-releases. Off unless you turn it on.
    public var beta = false
    /// A version not to offer again (you skipped it, or went back from it). Newer ones are offered as usual.
    public var skipped: String?

    public init(beta: Bool = false, skipped: String? = nil) {
        self.beta = beta
        self.skipped = skipped
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        beta = try c.decodeIfPresent(Bool.self, forKey: .beta) ?? false
        skipped = try c.decodeIfPresent(String.self, forKey: .skipped)
    }

    /// The saved choices; none saved, or a file that can't be read, means the defaults.
    public static func read(_ data: Data?) -> UpdateChoices {
        data.flatMap { try? JSONDecoder().decode(UpdateChoices.self, from: $0) } ?? UpdateChoices()
    }

    public func data() throws -> Data { try JSONEncoder().encode(self) }
}

public enum UpdateRules {
    /// GitHub's answer as releases: a list (GET /releases) or a single release (GET /releases/latest, or a test
    /// feed). Drafts and releases without a disk image for this Mac are left out.
    public static func releases(from json: Any) -> [Release] {
        let list = (json as? [[String: Any]]) ?? (json as? [String: Any]).map { [$0] } ?? []
        return list.filter { $0["draft"] as? Bool != true }.compactMap(release)
    }

    /// One release from GitHub's JSON, if it has the disk image for its own version. Other assets (a copy with a
    /// fixed name for a download page, another app's image) don't count.
    public static func release(_ json: [String: Any]) -> Release? {
        guard let tag = json["tag_name"] as? String, !tag.isEmpty else { return nil }
        let version = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        let assets = json["assets"] as? [[String: Any]] ?? []
        func asset(_ suffix: String) -> URL? {
            assets.first { ($0["name"] as? String)?.hasSuffix("-\(version)\(suffix)") == true }
                .flatMap { $0["browser_download_url"] as? String }.flatMap(URL.init(string:))
        }
        guard let dmg = asset("-arm64.dmg") else { return nil }
        return Release(version: version, prerelease: json["prerelease"] as? Bool ?? false,
                       notes: (json["html_url"] as? String).flatMap(URL.init(string:)), dmg: dmg,
                       checksum: asset("-arm64.dmg.sha256"))
    }

    /// The release to offer, if any: the newest one newer than `current`, never the skipped version, and a
    /// pre-release only with beta updates on.
    public static func offer(_ releases: [Release], current: String, beta: Bool, skipped: String?) -> Release? {
        releases
            .filter { beta || !$0.prerelease }
            .filter { release in skipped.map { !same(release.version, $0) } ?? true }
            .filter { isNewer($0.version, than: current) }
            .max { isNewer($1.version, than: $0.version) }
    }

    /// The skipped version while it still matters (it's newer than this one); nil once you're past it.
    public static func stillSkipped(_ skipped: String?, current: String) -> String? {
        guard let skipped, isNewer(skipped, than: current) else { return nil }
        return skipped
    }

    /// The version Go back returns to: the one the last update replaced (kept on this Mac), when it's older than
    /// this one. Nothing kept, or a copy that isn't older, means there's nothing to go back to.
    public static func goBack(kept: String?, current: String) -> String? {
        guard let kept, isNewer(current, than: kept) else { return nil }
        return kept
    }

    /// The server's answer to GET /api/jobs/busy. Only a clear yes counts: a server that doesn't answer (stopped,
    /// still starting, or a version without the route) has no work to lose.
    public static func busy(status: Int, body: Data) -> Bool {
        guard status == 200, let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any] else { return false }
        return json["busy"] as? Bool ?? false
    }

    /// Whether version a is higher than b: "0.10.0" is higher than "0.9.1", and "1.0" is the same as "1.0.0". A
    /// leading "v", and anything after a part's digits ("1-beta"), are ignored.
    public static func isNewer(_ a: String, than b: String) -> Bool {
        let x = parts(a), y = parts(b)
        for i in 0..<max(x.count, y.count) {
            let p = i < x.count ? x[i] : 0, q = i < y.count ? y[i] : 0
            if p != q { return p > q }
        }
        return false
    }

    public static func same(_ a: String, _ b: String) -> Bool { !isNewer(a, than: b) && !isNewer(b, than: a) }

    private static func parts(_ version: String) -> [Int] {
        let plain = version.hasPrefix("v") ? version.dropFirst() : Substring(version)
        return plain.split(separator: ".").map { Int(String($0.prefix { "0123456789".contains($0) })) ?? 0 }
    }
}
