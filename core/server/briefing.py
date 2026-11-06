"""The day's briefing: what each module has to say about today, what waits on you, what moved since a time, and what's
ahead. Each module gives its part through Module.brief(since, today) and the host merges the answers, the way search.py
does, so a page that starts the day (Traverse's Muster, or The Lodge's later) reads every module without knowing any.

    today     what's on today: due, late, in progress, today's meetings
    waiting   what waits on you: things to review, approve or choose
    moved     what happened since `since`: done, added, changed, removed, gone past due
    ahead     what's coming: due this week, milestones, cycles ending, projects at risk

A module answers {section: [entry, …]} for the sections it has something for. An entry is
    {"id", "what", "title"?, "href"?, "who"?, "when"?, "project"?, "kind"?, "tone"?, "minutes"?, "url"?}
    id       its thing's id in the module; the host makes the ref, "<module>:<id>"
    what     what happened, or why it's here, in a few words ("Due today", "To do → In progress")
    title    and href: filled from the module's describe when left out
    who      the person it's about or who did it ("Sam", "You"); when: an ISO day or time
    project  a name to group it under; kind: a short word the page may pick an icon by ("late", "done")
    tone     the family's: trail (late), sun (needs you), sky (in progress), forest (done), berry, neutral
    minutes  an estimate, for planning; url: where it opens outside the app
A module that fails is left out and named in "failed", never fatal.
"""
import logging
from datetime import date, datetime, timedelta, timezone

from . import module

log = logging.getLogger("core.briefing")

SECTIONS = ("today", "waiting", "moved", "ahead")
TONES = ("trail", "sun", "sky", "forest", "berry", "neutral")
FIELDS = ("what", "who", "when", "project", "kind", "tone", "minutes", "url")
MAX_ENTRIES = 80            # per module and section: a briefing is read, not searched


def stamp(moment: datetime) -> str:
    """A moment as the database writes them (db.now()): UTC, milliseconds, "Z"."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def day_before(now: datetime | None = None) -> str:
    """Twenty-four hours ago, for a briefing with nothing to go on (the very first one)."""
    return stamp((now or datetime.now(timezone.utc)) - timedelta(days=1))


def local_day(moment: str) -> date:
    """The calendar day on this computer of a stored moment ("2026-10-21T07:30:00.000Z" → 21 October)."""
    return datetime.fromisoformat(moment.replace("Z", "+00:00")).astimezone().date()


def gather(since: str | None = None, today: date | None = None) -> dict:
    """{"today", "since", "sections": {section: [entry…]}, "failed": [module names]}. Each entry gains "ref",
    "module" and "module_name", and a title and href when its module left them out."""
    today = today or date.today()
    since = since or day_before()
    sections: dict[str, list[dict]] = {s: [] for s in SECTIONS}
    failed = []
    for m in module.all_modules():
        if not m.brief:
            continue
        try:
            part = m.brief(since, today) or {}
            entries = {s: [_entry(m, e) for e in (part.get(s) or [])[:MAX_ENTRIES]] for s in SECTIONS}
        except Exception:  # noqa: BLE001 - one module's broken briefing shouldn't hide the others
            log.exception("The briefing failed in %s", m.id)
            failed.append(m.name)
            continue
        for s in SECTIONS:
            sections[s] += entries[s]
    return {"today": today.isoformat(), "since": since, "sections": sections, "failed": failed}


def _entry(m: module.Module, entry: dict) -> dict:
    ref = f"{m.id}:{entry['id']}"
    out = {"ref": ref, "module": m.id, "module_name": m.name, "title": entry.get("title"), "href": entry.get("href")}
    if not out["title"] or not out["href"]:
        described = module.describe(ref) or {}
        out["title"] = out["title"] or described.get("title") or "Something in " + m.name
        out["href"] = out["href"] or described.get("href")
    for key in FIELDS:
        out[key] = entry.get(key)
    if out["tone"] not in TONES:
        out["tone"] = "neutral"
    return out
