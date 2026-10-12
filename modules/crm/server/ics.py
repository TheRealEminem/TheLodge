"""Just enough of iCalendar (RFC 5545) to read a calendar's secret feed: events with a title, a start, the invitees
and whether they've declined, including repeating events within a window. No all-day events (they are not
meetings), and nothing is written back."""
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from dateutil import rrule

MAX_REPEATS = 400


@dataclass
class Invitee:
    email: str
    name: str | None = None
    status: str = "NEEDS-ACTION"      # ACCEPTED, DECLINED, TENTATIVE, NEEDS-ACTION


@dataclass
class Event:
    uid: str
    title: str
    start: datetime                    # always timezone-aware, UTC
    end: datetime | None
    invitees: list[Invitee] = field(default_factory=list)
    organizer: str | None = None
    cancelled: bool = False
    location: str | None = None

    @property
    def key(self) -> str:
        """Stable per occurrence: a repeating event is one uid with many starts."""
        return f"{self.uid}@{self.start.strftime('%Y%m%dT%H%M%SZ')}"


def _unfold(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    return lines


def _split(line: str) -> tuple[str, dict[str, str], str]:
    """NAME;PARAM=x:value -> (NAME, {PARAM: x}, value). Quoted parameter values may hold colons."""
    in_quote, cut = False, -1
    for i, ch in enumerate(line):
        if ch == '"':
            in_quote = not in_quote
        elif ch == ":" and not in_quote:
            cut = i
            break
    if cut < 0:
        return line.upper(), {}, ""
    head, value = line[:cut], line[cut + 1:]
    name, *params = re.split(r";(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)", head)
    return name.upper(), {k.upper(): v.strip('"') for k, _, v in (p.partition("=") for p in params)}, value


def _text(value: str) -> str:
    return value.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _when(value: str, params: dict[str, str]) -> datetime | None:
    """A date-time as UTC; None for a date alone (an all-day event)."""
    if params.get("VALUE") == "DATE" or re.fullmatch(r"\d{8}", value):
        return None
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        naive = datetime.strptime(value, "%Y%m%dT%H%M%S")
    except ValueError:
        return None
    try:
        zone = ZoneInfo(params["TZID"]) if params.get("TZID") else UTC
    except Exception:  # noqa: BLE001 - an unknown zone name: read it as UTC rather than lose the event
        zone = UTC
    return naive.replace(tzinfo=zone).astimezone(UTC)


def _mail(value: str) -> str | None:
    value = value.strip()
    if value.lower().startswith("mailto:"):
        value = value[7:]
    return value.lower() if "@" in value else None


def _components(lines: list[str]) -> list[list[tuple[str, dict[str, str], str]]]:
    events, current = [], None
    for line in lines:
        name, params, value = _split(line)
        if name == "BEGIN" and value.upper() == "VEVENT":
            current = []
        elif name == "END" and value.upper() == "VEVENT":
            if current is not None:
                events.append(current)
            current = None
        elif current is not None:
            current.append((name, params, value))
    return events


def parse(text: str, window_start: datetime, window_end: datetime) -> tuple[str | None, list[Event]]:
    """(the calendar's name, the events that start inside the window, repeats expanded and edits applied)."""
    lines = _unfold(text)
    calendar_name = next((_text(v) for n, _, v in map(_split, lines) if n in ("X-WR-CALNAME",)), None)
    masters: list[tuple[Event, str | None, list[datetime], timedelta | None]] = []   # event, rrule, exdates, length
    overrides: dict[tuple[str, datetime], Event] = {}
    for props in _components(lines):
        get = lambda name: next(((p, v) for n, p, v in props if n == name), None)  # noqa: E731
        start_prop = get("DTSTART")
        if not start_prop:
            continue
        start = _when(start_prop[1], start_prop[0])
        if start is None:
            continue
        end_prop = get("DTEND")
        end = _when(end_prop[1], end_prop[0]) if end_prop else None
        duration = (end - start) if end else None
        uid = (get("UID") or ({}, ""))[1] or f"{start.isoformat()}"
        event = Event(
            uid=uid, title=_text((get("SUMMARY") or ({}, "Busy"))[1]).strip() or "Busy", start=start, end=end,
            cancelled=((get("STATUS") or ({}, ""))[1].upper() == "CANCELLED"),
            organizer=_mail((get("ORGANIZER") or ({}, ""))[1]) if get("ORGANIZER") else None,
            location=_text((get("LOCATION") or ({}, ""))[1]).strip() or None,
        )
        for name, params, value in props:
            if name == "ATTENDEE" and (email := _mail(value)):
                event.invitees.append(Invitee(email, params.get("CN") or None, params.get("PARTSTAT", "NEEDS-ACTION").upper()))
        recurrence_id = get("RECURRENCE-ID")
        if recurrence_id:
            original = _when(recurrence_id[1], recurrence_id[0])
            if original:
                overrides[(uid, original)] = event
            continue
        rule = (get("RRULE") or ({}, None))[1]
        exdates = [d for n, p, v in props if n == "EXDATE" for part in v.split(",") if (d := _when(part, p))]
        masters.append((event, rule, exdates, duration))

    found: list[Event] = []
    for event, rule, exdates, duration in masters:
        starts = [event.start]
        if rule:
            try:
                rr = rrule.rrulestr(rule, dtstart=event.start)
                starts = list(rr.between(window_start - timedelta(days=1), window_end, inc=True))[:MAX_REPEATS]
            except (ValueError, TypeError):
                starts = [event.start]
        for s in starts:
            if s in exdates:
                continue
            occurrence = overrides.pop((event.uid, s), None)
            if occurrence is None:
                occurrence = Event(uid=event.uid, title=event.title, start=s, end=(s + duration) if duration else None,
                                   invitees=event.invitees, organizer=event.organizer, cancelled=event.cancelled,
                                   location=event.location)
            if window_start <= occurrence.start <= window_end:
                found.append(occurrence)
    # An edited instance whose master lies outside what we expanded (or has no master in the feed) still counts.
    for occurrence in overrides.values():
        if window_start <= occurrence.start <= window_end:
            found.append(occurrence)
    found.sort(key=lambda e: e.start)
    return calendar_name, found
