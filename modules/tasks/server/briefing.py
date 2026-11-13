"""The tasks module's part of the day's briefing (core/server/briefing.py, Module.brief): what's late, due today and
in progress for you; linked tasks waiting for you to choose; what got done and what was added since a moment; and
the week ahead: your due dates, milestones, and projects at risk.

"You" means what My tasks means: nobody's on it, or you are (items.MINE_SQL). Dates go in each entry's "when", so
the screen can say them its own way; "what" stays a few words.
"""
from datetime import date, timedelta

from core.server import db, module

from . import items, synced, vocab

WEEK = 7
SOURCE_WORDS = {"action-item": "Added from {source}", "linked": "Brought in from {source}", "ai": "Added by AI",
                "import": "Imported"}


def _open_sql() -> str:
    return f"status IN ({','.join(repr(s) for s in vocab.OPEN)})"


def _names() -> dict[str, str]:
    return {r["id"]: r["name"] for r in db.query("SELECT id, name FROM tasks_projects")}


def _who(item: dict) -> str | None:
    if item["assignee_ref"] == "core:me" or not (item["assignee_ref"] or item["assignee_name"]):
        return "You"
    return item["assignee_name"] or (module.describe(item["assignee_ref"]) or {}).get("title")


def _task(item: dict, names: dict, what: str, kind: str, tone: str = "neutral", when: str | None = None) -> dict:
    return {"id": item["id"], "title": item["text"], "what": what, "kind": kind, "tone": tone,
            "when": when or item["due_on"], "project": names.get(item["project_id"]), "who": _who(item),
            "minutes": item["estimate_min"]}


def brief(since: str, today: date) -> dict:
    names = _names()
    day, week = today.isoformat(), (today + timedelta(days=WEEK)).isoformat()
    mine = f"{_open_sql()} AND parent_id IS NULL AND {items.MINE_SQL}"

    on_today = []
    for item in db.query(f"SELECT * FROM tasks_items WHERE {mine} AND (due_on <= ? OR status = 'doing') "
                         "ORDER BY due_on IS NULL, due_on, priority DESC, sort", (day,)):
        if item["due_on"] and item["due_on"] < day:
            on_today.append(_task(item, names, "Late", "late", "trail"))
        elif item["due_on"] == day:
            on_today.append(_task(item, names, "Due today", "due", "sun"))
        else:
            on_today.append(_task(item, names, "Doing", "doing", "sky"))
    for ms in db.query("SELECT * FROM tasks_milestones WHERE done_at IS NULL AND due_on < ? ORDER BY due_on", (day,)):
        on_today.append({"id": ms["id"], "title": ms["name"], "what": "Milestone late", "kind": "late", "tone": "trail",
                         "when": ms["due_on"], "project": names.get(ms["project_id"])})

    waiting = []
    linked = synced.about([r["item_id"] for r in db.query("SELECT item_id FROM tasks_synced")])
    rows = {r["id"]: r for r in db.query(
        f"SELECT * FROM tasks_items WHERE id IN ({','.join('?' * len(linked))})", list(linked))} if linked else {}
    for item_id, about in linked.items():
        item = rows.get(item_id)
        if not item:
            continue
        if about["conflicts"]:
            fields = ", ".join(c["label"].lower() for c in about["conflicts"])
            waiting.append({**_task(item, names, f"Changed in {about['source']} too: {fields}", "flag", "sun"),
                            "url": about["url"]})
        elif about["removed_at"] and item["status"] in vocab.OPEN:
            waiting.append({**_task(item, names, f"Removed in {about['source']}", "removed", "neutral"),
                            "url": about["url"]})

    moved = []
    for item in db.query("SELECT * FROM tasks_items WHERE status = 'done' AND completed_at >= ? "
                         "ORDER BY completed_at DESC", (since,)):
        moved.append(_task(item, names, "Done", "done", "forest", item["completed_at"]))
    for item in db.query("SELECT * FROM tasks_items WHERE created_at >= ? AND status <> 'done' "
                         "ORDER BY created_at DESC", (since,)):
        source = (module.describe(item["source_ref"]) or {}).get("title") if item["source_ref"] else None
        if item["source"] == "linked":
            about = linked.get(item["id"])
            source = about["source"] if about else source
        words = SOURCE_WORDS.get(item["source"], "Added")
        what = words.format(source=source) if source or "{source}" not in words else "Added"
        moved.append(_task(item, names, what, "added", "neutral", item["created_at"]))
    for ms in db.query("SELECT * FROM tasks_milestones WHERE done_at >= ? ORDER BY done_at DESC", (since,)):
        moved.append({"id": ms["id"], "title": ms["name"], "what": "Milestone reached", "kind": "milestone",
                      "tone": "forest", "when": ms["done_at"], "project": names.get(ms["project_id"])})

    ahead = []
    for item in db.query(f"SELECT * FROM tasks_items WHERE {mine} AND status <> 'doing' AND due_on > ? AND due_on <= ? "
                         "ORDER BY due_on, priority DESC, sort", (day, week)):     # what you're doing is on today already
        ahead.append(_task(item, names, "Due", "due"))
    for ms in db.query("SELECT * FROM tasks_milestones WHERE done_at IS NULL AND due_on >= ? AND due_on <= ? "
                       "ORDER BY due_on", (day, week)):
        ahead.append({"id": ms["id"], "title": ms["name"], "what": "Milestone due", "kind": "milestone",
                      "tone": "sun" if ms["due_on"] == day else "neutral", "when": ms["due_on"],
                      "project": names.get(ms["project_id"])})
    for p in db.query("SELECT * FROM tasks_projects WHERE archived_at IS NULL AND status IN ('active', 'planned') "
                      "AND health IN ('at_risk', 'off_track') ORDER BY health DESC, due_on IS NULL, due_on"):
        label = vocab.HEALTH[p["health"]]["label"]
        ahead.append({"id": p["id"], "title": p["name"], "what": label, "kind": "at_risk",
                      "tone": "trail" if p["health"] == "off_track" else "sun", "when": p["due_on"],
                      "project": p["name"], "who": _owner(p)})

    return {"today": on_today, "waiting": waiting, "moved": moved, "ahead": ahead}


def _owner(project: dict) -> str | None:
    if project["owner_ref"] == "core:me":
        return "You"
    return project["owner_name"] or ((module.describe(project["owner_ref"]) or {}).get("title")
                                     if project["owner_ref"] else None)


def marked_done(payload: dict) -> None:
    """contracts.WORK_MARKED_DONE: a task ticked (or unticked) somewhere else, such as a pick in the day's plan."""
    module_id, _, item_id = (payload.get("ref") or "").partition(":")
    if module_id != "tasks":
        return
    row = db.one("SELECT status FROM tasks_items WHERE id = ?", (item_id,))
    if row is None:
        return
    if payload.get("done") and row["status"] != "done":
        items.set_status(item_id, "done")
    elif not payload.get("done") and row["status"] == "done":
        items.set_status(item_id, "todo")

