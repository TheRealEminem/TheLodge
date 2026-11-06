import AppKit
import EventKit
import WebKit

/// Your Mac's Calendar, read-only, for the page in the app's window. That's every account the Calendar app has
/// (iCloud, Google, Exchange…). The page asks through window.webkit.messageHandlers.calendar.postMessage({…}), which
/// answers with a promise (see core/web/api.ts):
///   {"ask": "access"}                          {"access"}, without asking macOS anything
///   {"ask": "request"}                         macOS asks you (once; after that it answers for you), then {"access"}
///   {"ask": "events", "from": ISO, "to": ISO}  {"access", "events": [{id, title, start, end, all_day, calendar, free}]}
///   {"ask": "settings"}                        opens System Settings at Privacy & Security → Calendars
/// "access" is "full", "unasked", "denied", "restricted", "write_only", or "unavailable" when this app doesn't use the
/// calendar (its app.json has no calendarUse, so its Info.plist has no reason for macOS to show, and asking would
/// end the app). Events you declined and cancelled ones are left out; "free" is an event that doesn't block time.
/// It never writes to the calendar and keeps nothing: every answer is read afresh, and only by this app's own page.
@MainActor
final class CalendarBridge: NSObject, WKScriptMessageHandlerWithReply {
    static let shared = CalendarBridge()
    private static let longest: TimeInterval = 31 * 24 * 3600   // the most one question may cover

    private var store = EKEventStore()

    static var usable: Bool { Bundle.main.object(forInfoDictionaryKey: "NSCalendarsFullAccessUsageDescription") != nil }

    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage,
                               replyHandler: @escaping @MainActor @Sendable (Any?, String?) -> Void) {
        guard Self.isOurs(message.frameInfo) else { return replyHandler(nil, "Only the app's own page can read the calendar.") }
        let body = message.body as? [String: Any] ?? [:]
        switch body["ask"] as? String {
        case "access":
            replyHandler(["access": Self.access()], nil)
        case "request":
            guard Self.usable, EKEventStore.authorizationStatus(for: .event) == .notDetermined else {
                return replyHandler(["access": Self.access()], nil)
            }
            NSApp.activate(ignoringOtherApps: true)   // macOS's question shows in front of the window that asked
            store.requestFullAccessToEvents { @Sendable _, _ in
                Task { @MainActor in
                    CalendarBridge.shared.store = EKEventStore()   // a store made before access sees no calendars
                    replyHandler(["access": Self.access()], nil)
                }
            }
        case "events":
            events(from: body["from"], to: body["to"], reply: replyHandler)
        case "settings":
            if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Calendars") {
                NSWorkspace.shared.open(url)
            }
            replyHandler(["access": Self.access()], nil)
        default:
            replyHandler(nil, "Ask for access, request, events or settings.")
        }
    }

    private func events(from: Any?, to: Any?, reply: @MainActor @Sendable (Any?, String?) -> Void) {
        let access = Self.access()
        guard access == "full" else { return reply(["access": access, "events": [Any]()], nil) }
        guard let start = Self.date(from), let end = Self.date(to), end > start, end.timeIntervalSince(start) <= Self.longest else {
            return reply(nil, "Ask for events between two moments, up to a month apart.")
        }
        let found = store.events(matching: store.predicateForEvents(withStart: start, end: end, calendars: nil))
            .filter { $0.status != .canceled && !Self.declined($0) }
            .sorted { $0.startDate < $1.startDate }
        reply(["access": access, "events": found.prefix(500).map(Self.shape)], nil)
    }

    // MARK: Helpers

    static func access() -> String {
        guard usable else { return "unavailable" }
        switch EKEventStore.authorizationStatus(for: .event) {
        case .fullAccess: return "full"
        case .notDetermined: return "unasked"
        case .restricted: return "restricted"
        case .writeOnly: return "write_only"
        case .denied: return "denied"
        @unknown default: return "denied"
        }
    }

    /// The page the window shows, not a frame or a page from somewhere else.
    private static func isOurs(_ frame: WKFrameInfo) -> Bool {
        let origin = frame.securityOrigin, server = AppConfig.serverURL
        let port = server.port ?? (server.scheme == "https" ? 443 : 80)
        return frame.isMainFrame && origin.host == server.host && (origin.port == port || (origin.port == 0 && server.port == nil))
    }

    private static func declined(_ event: EKEvent) -> Bool {
        event.attendees?.contains { $0.isCurrentUser && $0.participantStatus == .declined } ?? false
    }

    private static func shape(_ event: EKEvent) -> [String: Any] {
        let title = (event.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        return [
            "id": "\(event.calendarItemIdentifier)@\(Int(event.startDate.timeIntervalSince1970))",  // a repeat's each time
            "title": title.isEmpty ? "Busy" : title,
            "start": stamp(event.startDate),
            "end": stamp(event.endDate),
            "all_day": event.isAllDay,
            "calendar": event.calendar?.title ?? "",
            "free": event.availability == .free,
        ]
    }

    /// "2026-10-21T10:00:00+11:00": this Mac's own time, so a day's events read as the Calendar app shows them.
    private static func stamp(_ date: Date) -> String {
        let format = ISO8601DateFormatter()
        format.timeZone = .current
        return format.string(from: date)
    }

    /// An ISO moment from the page ("2026-10-21T13:00:00.000Z", or without the fraction).
    private static func date(_ value: Any?) -> Date? {
        guard let text = value as? String else { return nil }
        let format = ISO8601DateFormatter()
        format.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let found = format.date(from: text) { return found }
        format.formatOptions = [.withInternetDateTime]
        return format.date(from: text)
    }
}
