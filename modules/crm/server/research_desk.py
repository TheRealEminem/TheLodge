"""The Research page: everyone you could research, by how far their research has got, so you can pick a batch and
start a first pass with Gemini, deep research through an AI tool on your plan, or both, one after the other.

Where someone is:
    running   a run is queued, under way, or waiting on a limit or the budget
    deep      deep research is done: a run through an AI tool, or a report you added yourself
    first     only a first pass with Gemini so far
    skipped   snoozed, marked not worth it, or no surname yet
    new       no research at all
"""
from core.server import db

from . import gemini_research, research, views
from .connections import sort_key

SHOWS = ("new", "first", "deep", "running", "skipped")
WAITING = ("pending", "processing", "review")


def _mark(r: dict, waiting: set[str]) -> dict:
    return {"at": r["finished_at"] or r["created_at"], "via": r["via"], "inbox_id": r["inbox_id"],
            "waiting": r["inbox_id"] in waiting}


def desk(show: str = "new", q: str = "", limit: int = 50, offset: int = 0) -> dict:
    v = views.get()
    states = research.states(v)
    runs = db.query("SELECT * FROM crm_research_runs WHERE status != 'cancelled' ORDER BY created_at")
    waiting = {r["id"] for r in db.query(f"SELECT id FROM crm_inbox WHERE status IN {WAITING}")}
    latest, first, deep = {}, {}, {}
    for r in runs:                                        # oldest first, so the newest of each wins
        pid = r["entity_id"]
        latest[pid] = r
        if r["status"] == "done":
            (first if r["via"] == "api" else deep)[pid] = _mark(r, waiting)
    # Reports you brought in yourself (a Deep Research report pasted or dropped in) count as deep research.
    filed = {r["inbox_id"] for r in runs if r["inbox_id"]}
    for row in db.query(
            "SELECT id, coalesce(occurred_at, created_at) AS at, json_extract(result, '$.subject_id') AS pid FROM crm_inbox "
            f"WHERE status = 'applied' AND json_extract(proposal, '$.doc_type') IN {research.PROFILE_TYPES} "
            "ORDER BY created_at"):
        if row["pid"] and row["id"] not in filed and (row["pid"] not in deep or deep[row["pid"]]["at"] < row["at"]):
            deep[row["pid"]] = {"at": row["at"], "via": "you", "inbox_id": row["id"], "waiting": False}

    def where(pid: str) -> str:
        if latest.get(pid) and latest[pid]["status"] in gemini_research.UNFINISHED:
            return "running"
        if pid in deep:
            return "deep"
        if pid in first:
            return "first"
        if states[pid] in (research.SNOOZED, research.DISMISSED, research.NAME_NEEDED):
            return "skipped"
        return "new"

    places = {pid: where(pid) for pid in states if pid in v.conns}
    counts = {s: 0 for s in SHOWS}
    for s in places.values():
        counts[s] += 1
    needle = q.strip().lower()
    ids = [pid for pid, s in places.items() if s == show]
    if needle:
        org = lambda pid: (o.name if (o := v.employer(pid)) else "")  # noqa: E731
        ids = [pid for pid in ids if needle in v.snap.entities[pid].name.lower() or needle in org(pid).lower()]
    ids.sort(key=lambda pid: sort_key(v.conns[pid], v.snap.entities[pid].name))
    items = []
    for pid in ids[offset: offset + limit]:
        run = latest.get(pid)
        items.append({"row": v.person_row(pid), "state": states[pid], "first": first.get(pid), "deep": deep.get(pid),
                      "run": gemini_research._out(run) if run and run["status"] in (*gemini_research.UNFINISHED, "failed") else None})
    return {"show": show, "total": len(ids), "counts": counts, "items": items}
