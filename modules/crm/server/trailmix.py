"""Trailmix: meetings recorded on this Mac come in on their own.

Trailmix, the family's meeting recorder, keeps its meetings on this Mac and answers on localhost (crm.trailmix_url).
Once you turn it on, each run lists Trailmix's meetings, fetches the finished ones The Lodge hasn't seen (from the
last crm.trailmix_days days, 0 for all of them, counted from when you turned it on), and hands each to the same path as
a Granola meeting: the AI reads Trailmix's notes and transcript, and the result waits in the Inbox unless auto-add is
on. Meetings in the workspaces you leave out (crm.trailmix_skip_workspaces, such as Personal) never come in.

A meeting is remembered by Trailmix's permanent uid. One that Trailmix brought in from Granola also carries its
Granola id, so with both syncs on it still comes in once. Nothing leaves this Mac to fetch the meetings; reading them
uses the AI that reads everything else. Everything it creates is stamped source "trailmix" (see capture.py).
"""
import logging
from datetime import UTC, datetime, timedelta

import httpx

from core.server import db, jobs, settings

from . import capture, ingest, store
from .model import parse_dt

log = logging.getLogger("crm.trailmix")

PER_RUN = 40              # meetings handed to the AI in one run; a bigger backlog carries on at the next one
GENERIC = {"you", "me", "them", "others", "unknown"}

_transport: httpx.BaseTransport | None = None   # tests put a fake one here


class TrailmixError(RuntimeError):
    pass


def _cfg() -> dict:
    return settings.section("crm")


def configured() -> bool:
    return bool(_cfg()["trailmix_sync"])


def _client() -> httpx.Client:
    return httpx.Client(base_url=_cfg()["trailmix_url"].rstrip("/"), timeout=30, transport=_transport)


def _get(client: httpx.Client, path: str):
    try:
        r = client.get(path)
    except httpx.HTTPError as e:
        raise TrailmixError("Trailmix isn't answering on this Mac. Open Trailmix and its meetings come in at the next check.") from e
    if r.status_code in (401, 403):
        raise TrailmixError("Trailmix asks for a sign-in, which it only does when it's set up as a server. Point The Lodge "
                            "at the Trailmix on this Mac.")
    if r.status_code >= 400:
        raise TrailmixError(f"Trailmix answered {r.status_code}.")
    return r.json()


# ── Reading a meeting ─────────────────────────────────────────────────

def _names(m: dict) -> dict[str, str]:
    """Trailmix's speaker labels ("You", "Them", "Speaker 2") to the names it was given, with you as "Me"."""
    out = {}
    for label, name in (m.get("speaker_names") or {}).items():
        name = (name or "").strip()
        out[label] = "Me" if label == "You" else (name if name and name.lower() not in GENERIC else label)
    out.setdefault("You", "Me")
    return out


def transcript_text(m: dict) -> str:
    """One line per turn, adjacent lines from the same speaker joined; Trailmix's own text when it has no segments."""
    names = _names(m)
    lines: list[list[str]] = []
    for seg in m.get("segments") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        who = names.get(seg.get("speaker") or "", seg.get("speaker") or "Others")
        if lines and lines[-1][0] == who:
            lines[-1][1] += " " + text
        else:
            lines.append([who, text])
    return "\n".join(f"{who}: {text}" for who, text in lines) or (m.get("transcript") or "").strip()


def attendees_of(m: dict) -> list[dict]:
    """The people Trailmix put a name to. It has no invite, so the AI finds the rest in what was said."""
    names = _names(m)
    return [{"name": n, "email": None} for label, n in names.items()
            if label != "You" and n != label and not n.lower().startswith("speaker")]


def meeting_from(m: dict) -> dict:
    notes = (m.get("summary") or "").strip()
    tasks = [t["text"].strip() for t in m.get("tasks") or [] if (t.get("text") or "").strip()]
    if tasks and "action item" not in notes.lower():
        notes += "\n\n## Action items\n" + "\n".join(f"- {t}" for t in tasks)
    mine = [n.get("text", "").rstrip() for n in m.get("my_notes") or [] if (n.get("text") or "").strip()]
    if mine:
        notes += "\n\n## My notes during the meeting\n" + "\n".join(mine)
    from_granola = m.get("source") == "granola" and m.get("external_id")
    return {
        "origin": "trailmix",
        "external_id": m["uid"],
        "also": {"granola": m["external_id"]} if from_granola else None,
        "title": m.get("title"),
        "started_at": m.get("created_at"),
        "attendees": attendees_of(m),
        "notes": notes.strip() or None,
        "transcript": transcript_text(m) or None,
    }


# ── The sync ──────────────────────────────────────────────────────────

def _seen(uid: str) -> bool:
    return db.one("SELECT 1 AS x FROM crm_inbox WHERE source = 'meeting' AND json_extract(payload, '$.origin') = 'trailmix' "
                  "AND json_extract(payload, '$.external_id') = ?", (uid,)) is not None


def _since(state: dict, now: datetime) -> datetime | None:
    """The oldest meeting to bring in: set when the first run happens, so later runs don't creep forward."""
    if state.get("window_from"):
        return datetime.fromisoformat(state["window_from"])
    days = int(_cfg()["trailmix_days"] or 0)
    return now - timedelta(days=days) if days > 0 else None


def sync() -> dict:
    """One pass. Never raises for what's wrong with Trailmix: it records it for the Settings page."""
    if not configured():
        return {"skipped": "off"}
    now = datetime.now(UTC)
    state = capture.get_state("trailmix")
    since = _since(state, now)
    skip = {int(w) for w in _cfg()["trailmix_skip_workspaces"] or []}
    auto = bool(_cfg()["trailmix_auto_apply"])
    counts = {"checked": 0, "imported": 0, "known": 0, "not_ready": 0, "failed": 0, "left_out": 0, "later": 0}
    try:
        with _client() as client:
            listed = _get(client, "/api/meetings")
            listed.sort(key=lambda m: m.get("created_at") or "")
            for row in listed:
                when = parse_dt(row.get("created_at"))
                if since and when and when < since:
                    continue
                counts["checked"] += 1
                if row.get("workspace_id") in skip:
                    counts["left_out"] += 1
                    continue
                if row.get("status") != "done":
                    counts["not_ready"] += 1
                    continue
                if counts["imported"] >= PER_RUN:
                    counts["later"] += 1
                    continue
                try:
                    m = _get(client, f"/api/meetings/{row['id']}")
                    if not m.get("uid") or _seen(m["uid"]):
                        counts["known"] += 1
                        continue
                    meeting = meeting_from(m)
                    if not (meeting["notes"] or meeting["transcript"]):
                        counts["not_ready"] += 1
                        continue
                    _, already = ingest.create_meeting_job(**meeting, auto_apply=auto)
                    counts["known" if already else "imported"] += 1
                except TrailmixError:
                    raise
                except Exception:  # noqa: BLE001 - one odd meeting must not stop the rest
                    log.exception("could not bring in Trailmix meeting %s", row.get("id"))
                    counts["failed"] += 1
        counts["total"] = db.one("SELECT count(*) AS n FROM crm_inbox WHERE source = 'meeting' "
                                 "AND json_extract(payload, '$.origin') = 'trailmix'")["n"]
        capture.set_state("trailmix", error=None, last_ok_at=db.now(), last_counts=counts,
                          window_from=(since or datetime(2000, 1, 1, tzinfo=UTC)).isoformat())
    except TrailmixError as e:
        capture.set_state("trailmix", error=str(e))
        log.warning("Trailmix sync: %s", e)
    capture.set_state("trailmix", last_run_at=db.now())
    return counts


def handle_sync(job: jobs.Job) -> None:
    job.stage("Checking Trailmix")
    sync()


def seconds() -> int:
    """Every 15 minutes once it's on (every 5 while a backlog is left); never before."""
    if not configured():
        return 0
    return 300 if (capture.get_state("trailmix").get("last_counts") or {}).get("later") else 900


def test() -> dict:
    """Is Trailmix there? Its meetings and workspaces, so Settings can say what would come in. Imports nothing."""
    with _client() as client:
        meetings = _get(client, "/api/meetings")
        try:
            spaces = _get(client, "/api/workspaces")
        except TrailmixError:
            spaces = []
    me = store.get_me()
    return {"ok": True, "meetings": len(meetings), "done": sum(1 for m in meetings if m.get("status") == "done"),
            "workspaces": [{"id": w["id"], "name": w["name"], "meetings": w.get("meetings", 0)} for w in spaces],
            "unsorted": sum(1 for m in meetings if m.get("workspace_id") is None), "has_me": bool(me)}
