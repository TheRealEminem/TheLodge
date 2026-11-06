// Checks the updater's decisions (Sources/UpdateRules) with the Command Line Tools alone, no XCTest:
//   swift run --package-path mac UpdateChecks
// scripts/build-app.sh runs it after building, so a release can't go out with these broken.
import Foundation
import UpdateRules

var failures = 0

func check(_ ok: Bool, _ text: String, line: Int = #line) {
    print((ok ? "  OK   " : "  FAIL ") + text + (ok ? "" : " (main.swift:\(line))"))
    if !ok { failures += 1 }
}

func section(_ title: String) { print(title) }

/// A release as GitHub's API returns it.
func github(_ tag: String, prerelease: Bool = false, draft: Bool = false, name: String = "Traverse",
            assets: [String]? = nil) -> [String: Any] {
    let version = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
    let files = assets ?? ["\(name)-\(version)-arm64.dmg", "\(name)-\(version)-arm64.dmg.sha256"]
    return ["tag_name": tag, "prerelease": prerelease, "draft": draft,
            "html_url": "https://github.com/o/r/releases/tag/\(tag)",
            "assets": files.map { ["name": $0, "browser_download_url": "https://example.test/\($0)"] }]
}

func offered(_ list: [[String: Any]], current: String, beta: Bool = false, skipped: String? = nil) -> String? {
    UpdateRules.offer(UpdateRules.releases(from: list), current: current, beta: beta, skipped: skipped)?.version
}

section("Versions")
check(UpdateRules.isNewer("0.10.0", than: "0.9.1"), "0.10.0 is newer than 0.9.1 (numbers, not text)")
check(!UpdateRules.isNewer("1.0", than: "1.0.0") && UpdateRules.same("1.0", "1.0.0"), "1.0 and 1.0.0 are the same")
check(UpdateRules.isNewer("v0.2.0", than: "0.1.9"), "a leading v is ignored")
check(!UpdateRules.isNewer("0.2.0", than: "0.2.0"), "a version isn't newer than itself")
check(UpdateRules.isNewer("1.2.1", than: "1.2"), "1.2.1 is newer than 1.2")

section("Reading GitHub's answer")
let one = UpdateRules.releases(from: github("v0.3.0", prerelease: true))
check(one.count == 1 && one[0].version == "0.3.0" && one[0].prerelease, "a single release (releases/latest, a test feed)")
check(one.first?.checksum?.lastPathComponent == "Traverse-0.3.0-arm64.dmg.sha256", "its checksum is found")
check(UpdateRules.releases(from: [github("v0.3.0", draft: true), github("v0.2.0")]).map(\.version) == ["0.2.0"],
      "drafts are left out")
check(UpdateRules.releases(from: [github("v0.3.0", assets: ["Traverse-arm64.dmg"])]).isEmpty,
      "a release whose only image has no version in its name isn't offered (a fixed-name copy for a download page)")
check(UpdateRules.releases(from: [github("v0.2.0", assets: ["Traverse-10.2.0-arm64.dmg"])]).isEmpty,
      "an image for another version (10.2.0 for 0.2.0) doesn't count")
check(UpdateRules.releases(from: [github("v0.2.0", name: "The.Lodge")]).count == 1,
      "a name GitHub rewrote (spaces to dots) still matches")
check(UpdateRules.releases(from: [github("v0.2.0", assets: ["Traverse-0.2.0-arm64.dmg"])]).first?.checksum == nil,
      "a missing checksum is noticed (the updater then refuses to install)")
check(UpdateRules.releases(from: ["message": "API rate limit exceeded"]).isEmpty, "an error from GitHub is no release")

section("Which version is offered")
let feed = [github("v0.4.0", prerelease: true), github("v0.3.0"), github("v0.2.0")]
check(offered(feed, current: "0.2.0") == "0.3.0", "beta updates off: the newest full release")
check(offered(feed, current: "0.2.0", beta: true) == "0.4.0", "beta updates on: the newest pre-release too")
check(offered(feed, current: "0.3.0") == nil, "beta updates off, on the newest full release: nothing")
check(offered([github("v0.5.0"), github("v0.4.0", prerelease: true)], current: "0.3.0", beta: true) == "0.5.0",
      "beta updates on, and a full release is newer than the newest beta: the full release")
check(offered(feed, current: "0.4.0", beta: true) == nil, "already on the newest: nothing")
check(offered(feed, current: "0.5.0", beta: true) == nil, "older releases are never offered as updates")
check(offered([], current: "0.1.0") == nil, "no releases: nothing")

section("Skipping")
check(offered(feed, current: "0.2.0", skipped: "0.3.0") == nil, "the skipped version isn't offered")
check(offered(feed, current: "0.2.0", beta: true, skipped: "0.4.0") == "0.3.0",
      "skipping the newest still offers the next newest")
check(offered([github("v0.3.1"), github("v0.3.0")], current: "0.2.0", skipped: "0.3.0") == "0.3.1",
      "a version newer than the skipped one is offered")
check(offered(feed, current: "0.2.0", skipped: "v0.3.0") == nil, "a skip written with a v still matches")
check(UpdateRules.stillSkipped("0.3.0", current: "0.2.0") == "0.3.0", "a skip ahead of this version still matters")
check(UpdateRules.stillSkipped("0.3.0", current: "0.3.1") == nil, "once past the skipped version, it's forgotten")
check(UpdateRules.stillSkipped(nil, current: "0.3.0") == nil, "nothing skipped")

section("Going back")
check(UpdateRules.goBack(kept: "0.2.0", current: "0.3.0") == "0.2.0", "the version the last update replaced")
check(UpdateRules.goBack(kept: nil, current: "0.3.0") == nil, "nothing kept (a fresh install): nothing to go back to")
check(UpdateRules.goBack(kept: "0.3.0", current: "0.3.0") == nil, "a kept copy of this same version isn't offered")
check(UpdateRules.goBack(kept: "0.4.0", current: "0.3.0") == nil, "a kept copy newer than this one isn't \"back\"")

section("Your choices")
check(UpdateChoices.read(nil) == UpdateChoices(beta: false, skipped: nil), "nothing saved: beta updates off, nothing skipped")
check(UpdateChoices.read(Data("{}".utf8)).beta == false, "a file without the choice: beta updates off")
check(UpdateChoices.read(Data("not json".utf8)) == UpdateChoices(), "an unreadable file: the defaults")
let saved = UpdateChoices(beta: true, skipped: "0.4.0")
check(UpdateChoices.read(try? saved.data()) == saved, "choices read back as saved")

section("Busy")
check(UpdateRules.busy(status: 200, body: Data(#"{"busy": true}"#.utf8)), "the server says it's busy: busy")
check(!UpdateRules.busy(status: 200, body: Data(#"{"busy": false}"#.utf8)), "the server says it isn't: not busy")
check(!UpdateRules.busy(status: 404, body: Data("Not Found".utf8)), "a server without the route: not busy")
check(!UpdateRules.busy(status: 401, body: Data(#"{"busy": true}"#.utf8)), "an answer that isn't a 200 doesn't count")
check(!UpdateRules.busy(status: 200, body: Data("<html>".utf8)), "an answer that isn't JSON: not busy")

section("Lockdown")
check(UpdateRules.lockedDown(status: 200, body: Data(#"{"on": true, "parked": 0}"#.utf8)) == true, "the server says Lockdown is on: on")
check(UpdateRules.lockedDown(status: 200, body: Data(#"{"on": false, "parked": 2}"#.utf8)) == false, "the server says it's off: off")
check(UpdateRules.lockedDown(status: 404, body: Data("Not Found".utf8)) == nil, "a server without the route can't say")
check(UpdateRules.lockedDown(status: 503, body: Data(#"{"on": false}"#.utf8)) == nil, "an answer that isn't a 200 can't say")
check(UpdateRules.lockedDown(status: 200, body: Data("<html>".utf8)) == nil, "an answer that isn't JSON can't say")
check(UpdateRules.lockedDown(status: 200, body: Data(#"{"on": "no"}"#.utf8)) == nil, "an answer without a yes or no can't say")

print(failures == 0 ? "\nAll good." : "\n\(failures) problem(s).")
exit(failures == 0 ? 0 : 1)
