"""What the AI drafts for you to look over (Traverse PLAN.md chunk 12): a project's status update, and a task broken
down into subtasks. Nothing it writes counts until you say so.

- "Draft a status" runs the tasks/draft job, which reads the project (how far along it is, its milestones, what got
  done or added since the last status update, what's late, tasks that are blocked, waiting or changed elsewhere, and
  the latest updates) and asks the AI (Settings → AI) for a short update and a suggested health. You edit it, discard
  it, or post it as the project's status update, which keeps saying which AI drafted it.
- "Break it down" runs the same job for a task: the AI proposes subtasks with estimates; you accept, edit or drop each,
  and accepted ones become the task's subtasks (source "ai"). Subtasks stay here.

One draft of each kind per project or task: drafting again replaces it (a breakdown keeps what you've decided). The AI
runs only in the job, never in a request, and what it wrote always carries `written_by`. Running the job twice just
drafts again.
"""
import json
import re
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field

from core.server import ai, db, jobs
from core.server.jobs import Job

from . import items, projects, store, synced, vocab

KIND = "draft"
MAX_SUBTASKS = 8
LIST_CAP = 20                    # items per list in the status prompt; the rest are counted
PROPOSAL_STATES = ("proposed", "accepted", "dropped")


def lane(_target: str) -> str:
    """Someone is waiting for a draft, but a model on this Mac runs one thing at a time."""
    return "default" if ai.local_first() else "interactive"


def written_by(pid: str) -> str:
    """"Claude · claude-sonnet-5-5": which AI wrote it, as the screens show it."""
    about = ai.describe(pid)
    return f"{about['label']} · {about['model']}" if about.get("model") else about["label"]


# ── The drafts ────────────────────────────────────────────────────────

def _row(draft_id: str) -> dict | None:
    return db.one("SELECT * FROM tasks_drafts WHERE id = ?", (draft_id,))


def _get(draft_id: str) -> dict:
    row = _row(draft_id)
    if row is None:
        raise KeyError(draft_id)
    return row


def _owner(row: dict) -> str | None:
    """The project a draft belongs to (for tasks.changed)."""
    if row["project_id"]:
        return row["project_id"]
    item = db.one("SELECT project_id FROM tasks_items WHERE id = ?", (row["item_id"],))
    return item["project_id"] if item else None


def _set(draft_id: str, **cols) -> None:
    if "proposals" in cols:
        cols["proposals"] = json.dumps(cols["proposals"])
    cols["updated_at"] = db.now()
    db.execute(f"UPDATE tasks_drafts SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", (*cols.values(), draft_id))
    row = _row(draft_id)
    if row:
        store.changed(_owner(row), draft_id=draft_id)


def shaped(row: dict | None) -> dict | None:
    """A draft as the screens show it, with its job (drafting, failed with why, or done)."""
    if row is None:
        return None
    return {**dict(row), "proposals": json.loads(row["proposals"]), "edited": bool(row["edited"]),
            "job": jobs.latest("tasks", [row["id"]]).get(row["id"])}


def for_project(project_id: str) -> dict | None:
    return shaped(db.one("SELECT * FROM tasks_drafts WHERE kind = 'status' AND project_id = ?", (project_id,)))


def for_item(item_id: str) -> dict | None:
    return shaped(db.one("SELECT * FROM tasks_drafts WHERE kind = 'breakdown' AND item_id = ?", (item_id,)))


def _start(kind: str, column: str, owner_id: str, keep: list[dict]) -> dict:
    """Makes or resets the one draft of `kind` for a project or task, and queues the job that writes it."""
    row = db.one(f"SELECT id FROM tasks_drafts WHERE kind = ? AND {column} = ?", (kind, owner_id))
    if row:
        draft_id = row["id"]
        jobs.cancel_for("tasks", draft_id)      # (one already running finishes, and this one follows it)
        _set(draft_id, status="drafting", body="", health=None, why=None, proposals=keep, written_by=None, edited=0)
    else:
        draft_id, now = db.new_id(), db.now()
        db.execute(f"INSERT INTO tasks_drafts (id, kind, {column}, status, proposals, created_at, updated_at) "
                   f"VALUES (?, ?, ?, 'drafting', ?, ?, ?)", (draft_id, kind, owner_id, json.dumps(keep), now, now))
        store.changed(_owner(_get(draft_id)), draft_id=draft_id)
    jobs.enqueue("tasks", KIND, draft_id)
    return shaped(_get(draft_id))


def start_status(project_id: str) -> dict:
    """"Draft a status": a new draft of the project's status update (any draft it had is replaced)."""
    if not db.one("SELECT 1 FROM tasks_projects WHERE id = ?", (project_id,)):
        raise KeyError(project_id)
    return _start("status", "project_id", project_id, [])


def start_breakdown(item_id: str) -> dict:
    """"Break it down": new proposed subtasks for a task. Ones you've accepted or dropped stay decided."""
    if items.get(item_id) is None:
        raise KeyError(item_id)
    old = for_item(item_id)
    keep = [p for p in (old or {}).get("proposals", []) if p["state"] != "proposed"]
    return _start("breakdown", "item_id", item_id, keep)


def edit(draft_id: str, changes: dict) -> dict:
    """Your changes to a status draft: {"body"?, "health"?}. It still says who drafted it, and that you edited it."""
    row = _get(draft_id)
    if row["kind"] != "status" or row["status"] != "ready":
        raise ValueError("That draft isn't ready to edit")
    unknown = set(changes) - {"body", "health"}
    if unknown:
        raise ValueError(f"Can't change {', '.join(sorted(unknown))}")
    cols: dict = {}
    if "body" in changes:
        cols["body"] = store.words(changes["body"], "A draft")
    if "health" in changes:
        cols["health"] = None if changes["health"] in (None, "") else store.one_of(changes["health"], vocab.HEALTH, "Health")
    if any(cols[k] != row[k] for k in cols):
        _set(draft_id, **cols, edited=1)
    return shaped(_get(draft_id))


def discard(draft_id: str) -> bool:
    row = _row(draft_id)
    if row is None:
        return False
    jobs.cancel_for("tasks", draft_id)
    db.execute("DELETE FROM tasks_drafts WHERE id = ?", (draft_id,))
    store.changed(_owner(row), draft_id=draft_id)
    return True


def post(draft_id: str, share_on: str | None = None) -> dict:
    """Posts a status draft as the project's status update (its health becomes the project's), and forgets the draft.
    share_on: one of the project's linked tasks, whose other side gets it as a new comment once you approve it there
    (synced.comment). Returns the update."""
    row = _get(draft_id)
    if row["kind"] != "status" or row["status"] != "ready":
        raise ValueError("That draft isn't ready to post")
    if not row["body"].strip():
        raise ValueError("The draft is empty. Write something, or discard it.")
    if share_on:
        synced.can_comment(share_on, project_id=row["project_id"])   # before posting, so a wrong choice posts nothing
    update = projects.add_update(project_id=row["project_id"], kind="status", body=row["body"].strip(),
                                 health=row["health"], author_ref="core:me", written_by=row["written_by"],
                                 edited=bool(row["edited"]))
    discard(draft_id)
    if share_on:
        update["asked"] = synced.comment(update["id"], share_on)
    return update


# ── A breakdown's proposals ───────────────────────────────────────────

def _proposal(proposals: list[dict], proposal_id: str) -> dict:
    found = next((p for p in proposals if p["id"] == proposal_id), None)
    if found is None:
        raise KeyError(proposal_id)
    return found


def edit_proposal(draft_id: str, proposal_id: str, changes: dict) -> dict:
    """{"text"?, "estimate_min"?, "state"?: "proposed" | "dropped"} for one proposed subtask."""
    row = _get(draft_id)
    if row["kind"] != "breakdown":
        raise ValueError("That draft has no proposed subtasks")
    unknown = set(changes) - {"text", "estimate_min", "state"}
    if unknown:
        raise ValueError(f"Can't change {', '.join(sorted(unknown))}")
    proposals = json.loads(row["proposals"])
    p = _proposal(proposals, proposal_id)
    if p["state"] == "accepted":
        raise ValueError("That one is a subtask already. Change it there.")
    if "text" in changes:
        p["text"] = store.text(changes["text"], "A subtask")
        p["edited"] = True
    if "estimate_min" in changes:
        p["estimate_min"] = store.minutes(changes["estimate_min"])
        p["edited"] = True
    if "state" in changes:
        p["state"] = store.one_of(changes["state"], ("proposed", "dropped"), "state")
    _set(draft_id, proposals=proposals)
    return shaped(_get(draft_id))


def accept(draft_id: str, proposal_ids: list[str] | None = None) -> dict:
    """Makes these proposals (all those still proposed when None) the task's subtasks, in the order proposed."""
    row = _get(draft_id)
    if row["kind"] != "breakdown":
        raise ValueError("That draft has no proposed subtasks")
    if items.get(row["item_id"]) is None:
        raise KeyError(row["item_id"])
    proposals = json.loads(row["proposals"])
    wanted = [p for p in proposals if p["state"] == "proposed" and (proposal_ids is None or p["id"] in proposal_ids)]
    if proposal_ids is not None:
        for pid in proposal_ids:
            if _proposal(proposals, pid)["state"] != "proposed":
                raise ValueError("That one isn't waiting for you any more")
    for p in wanted:
        p["item_id"] = items.create(p["text"], parent_id=row["item_id"], estimate_min=p.get("estimate_min"),
                                    source="ai", attributes={"written_by": row["written_by"], "edited": p.get("edited", False)},
                                    quiet=True)
        p["state"] = "accepted"
    _set(draft_id, proposals=proposals)
    return shaped(_get(draft_id))


# ── The job ───────────────────────────────────────────────────────────

def write(job: Job) -> None:
    """tasks/draft: asks the AI for the draft. A draft discarded meanwhile is left alone."""
    row = _row(job.target)
    if row is None:
        return
    job.stage("Reading the project" if row["kind"] == "status" else "Reading the task")
    (_write_status if row["kind"] == "status" else _write_breakdown)(row, job)


# A status update

STATUS_SYSTEM = """You draft a project's status update for the person who runs it. They will read it, edit it, and
post it under their own name to their team, so write in their voice ("we"), plainly, without hype.

- body: Markdown, under 150 words. Start with one sentence on where the project stands. Then short bullet lists under
  these bold labels: **Done** (finished since the last update), **Next** (in progress or due soon), **Watch** (late
  tasks, blockers, things waiting on others, anything changed elsewhere). Leave a label out when nothing goes under
  it; never write "Nothing" or "None". Name tasks by their titles and people by name; "me" in the facts is the person
  posting it. The health and its reason go in their own fields, not in body. Use only what the facts say; never
  invent work or dates.
- why: one sentence, the main reason for the health you suggest.
- health: on_track, at_risk or off_track. Late tasks, a missed or slipping milestone, or blockers point to at_risk;
  the project's own due date passed or most of the work late points to off_track. Little to go on: on_track."""


class StatusDraft(BaseModel):
    """The reasons come before the health, so a model that fills the schema in order decides last."""
    body: str
    why: str
    health: str = Field(description="on_track, at_risk or off_track")


def _day(iso: str | None) -> str:
    return iso[:10] if iso else ""


def _listed(rows: list[dict], line) -> list[str]:
    out = [line(r) for r in rows[:LIST_CAP]]
    return out + ([f"- and {len(rows) - LIST_CAP} more"] if len(rows) > LIST_CAP else [])


def _who(r: dict) -> str:
    """Who a task is with, in the prompt: "me" is whoever posts the update (it's written in their voice)."""
    if r["assignee_ref"] == "core:me":
        return "me"
    return r["assignee_name"] or ("" if not r["assignee_ref"] else "someone")


def _task_line(r: dict, *, due=True) -> str:
    bits = [b for b in (_who(r), f"due {r['due_on']}" if due and r["due_on"] else "") if b]
    return f"- {r['text']}" + (f" ({', '.join(bits)})" if bits else "")


def status_prompt(project_id: str) -> str:
    """The facts a status update is drafted from, as plain text."""
    p = projects.get(project_id)
    today = items.today()
    roll = p["rollup"]
    last = db.one("SELECT created_at FROM tasks_updates WHERE project_id = ? AND kind = 'status' "
                  "ORDER BY created_at DESC LIMIT 1", (project_id,))
    fortnight = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    since = last["created_at"] if last else fortnight
    lines = [f"TODAY: {today:%A} {today.isoformat()}", f"PROJECT: {p['name']}"]
    if p["summary"]:
        lines.append(f"WHAT DONE LOOKS LIKE: {p['summary']}")
    status = vocab.PROJECT_STATUSES[p["status"]]["label"]
    lines.append(f"STATUS: {status}" + (f"; health last reported: {vocab.HEALTH[p['health']]['label']}" if p["health"] else ""))
    dates = [f"started {p['start_on']}" if p["start_on"] else "", f"due {p['due_on']}" if p["due_on"] else ""]
    if any(dates):
        lines.append("DATES: " + ", ".join(d for d in dates if d))
    if p["owner_name"]:
        lines.append(f"OWNER: {p['owner_name']}")
    if p["brief"].strip():
        brief = p["brief"].strip()
        lines += ["BRIEF:", brief if len(brief) <= 1500 else brief[:1500].rstrip() + "…"]
    by = roll["by_status"]
    pct = f"{round(roll['progress'] * 100)}% done" if roll["progress"] is not None else "nothing to count yet"
    lines.append(f"PROGRESS: {roll['done']} of {roll['counted']} tasks done ({pct}); {by['doing']} doing, "
                 f"{by['waiting']} waiting, {by['todo']} to do, {roll['late']} late")

    if p["milestones"]:
        lines.append("MILESTONES:")
        for m in p["milestones"]:
            r = m["rollup"]
            state = "reached" if m["done"] else ("missed: due " + m["due_on"] if m["due_on"] and m["due_on"] < today.isoformat()
                                                 else (f"due {m['due_on']}" if m["due_on"] else "no date"))
            lines.append(f"- {m['name']}: {state}; {r['done']} of {r['counted']} done" + (f", {r['late']} late" if r["late"] else ""))

    def tasks(sql: str, args: tuple) -> list[dict]:
        return db.query(f"SELECT * FROM tasks_items WHERE project_id = ? AND parent_id IS NULL AND {sql}",
                        (project_id, *args))

    since_words = f"since the last status update ({_day(since)})" if last else "in the last two weeks"
    done = tasks("status = 'done' AND completed_at >= ? ORDER BY completed_at", (since,))
    lines.append(f"DONE {since_words.upper()}:")
    lines += _listed(done, lambda r: _task_line(r, due=False)) or ["- nothing"]
    added = tasks("created_at >= ? AND status <> 'done' ORDER BY created_at", (since,))
    if added:
        lines.append(f"ADDED {since_words.upper()}:")
        lines += _listed(added, _task_line)
    open_sql = f"status IN ({','.join('?' * len(vocab.OPEN))})"
    late = tasks(f"{open_sql} AND due_on < ? ORDER BY due_on", (*vocab.OPEN, today.isoformat()))
    if late:
        lines.append("LATE:")
        lines += _listed(late, _task_line)
    doing = tasks("status = 'doing' ORDER BY due_on IS NULL, due_on, sort", ())
    if doing:
        lines.append("IN PROGRESS:")
        lines += _listed(doing, _task_line)
    soon = tasks(f"{open_sql} AND due_on >= ? AND due_on <= ? ORDER BY due_on",
                 (*vocab.OPEN, today.isoformat(), (today + timedelta(days=14)).isoformat()))
    if soon:
        lines.append("DUE IN THE NEXT TWO WEEKS:")
        lines += _listed(soon, _task_line)

    flags = _flags(project_id)
    if flags:
        lines.append("FLAGS:")
        lines += _listed(flags, lambda f: f)

    recent = db.query("SELECT * FROM tasks_updates WHERE project_id = ? ORDER BY created_at DESC LIMIT 3", (project_id,))
    if recent:
        lines.append("LATEST UPDATES (newest first):")
        for u in recent:
            health = f", {vocab.HEALTH[u['health']]['label']}" if u["health"] else ""
            body = " ".join(u["body"].split())
            lines.append(f"- {_day(u['created_at'])} ({u['kind']}{health}): {body[:600]}")
    return "\n".join(lines)


def _flags(project_id: str) -> list[str]:
    """Open tasks someone should hear about: blocked, waiting, and linked ones changed or gone elsewhere."""
    open_rows = db.query(f"SELECT * FROM tasks_items WHERE project_id = ? AND parent_id IS NULL AND status IN "
                         f"({','.join('?' * len(vocab.OPEN))}) ORDER BY sort", (project_id, *vocab.OPEN))
    if not open_rows:
        return []
    ids = [r["id"] for r in open_rows]
    marks = ",".join("?" * len(ids))
    waits = {}
    for b in db.query(f"SELECT b.item_id, i.text FROM tasks_blockers b JOIN tasks_items i ON i.id = b.blocked_by "
                      f"WHERE b.item_id IN ({marks}) AND i.status IN ({','.join('?' * len(vocab.OPEN))})", (*ids, *vocab.OPEN)):
        waits.setdefault(b["item_id"], []).append(b["text"])
    linked = synced.about(ids)
    out = []
    for r in open_rows:
        notes = []
        if r["id"] in waits:
            notes.append("blocked by " + "; ".join(waits[r["id"]]))
        if r["status"] == "waiting":
            notes.append("waiting" + (f" on {_who(r)}" if _who(r) not in ("", "me") else ""))
        about = linked.get(r["id"])
        if about and about["removed_at"]:
            notes.append(f"removed in {about['source']}")
        if about and about["conflicts"]:
            notes.append(f"changed both here and in {about['source']}: " + ", ".join(c["label"].lower() for c in about["conflicts"]))
        if notes:
            out.append(f"- {r['text']}: {'; '.join(notes)}")
    return out


_LABEL = re.compile(r"^\s*\*\*[^*]+?:?\*\*:?\s*$")                      # "**Done**", "**Done:**", "**Done**:"
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_HEALTH_LINE = re.compile(r"^\s*\**\s*health\s*\**\s*:", re.I)              # "**Health:** at_risk"
_NOTHING = {"nothing", "none", "n/a", "nothing yet", "none yet", "nothing to report", "-"}


def tidy_body(text: str) -> str:
    """What a model (small local ones especially) adds that the draft says elsewhere or that says nothing: a line
    giving the health (the draft has its own), and a label with nothing, or only "Nothing", under it."""
    lines = [ln.rstrip() for ln in (text or "").replace("\r\n", "\n").split("\n")]
    out: list[str] = []
    i = 0
    while i < len(lines):
        if _HEALTH_LINE.match(lines[i]):
            i += 1
            continue
        if _LABEL.match(lines[i]):
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            k = j
            while k < len(lines) and _BULLET.match(lines[k]) and not _LABEL.match(lines[k]):
                k += 1
            said = [_BULLET.match(ln)[1].strip(" .*_").casefold() for ln in lines[j:k]]
            empty = all(s in _NOTHING for s in said) if said else (k >= len(lines) or _LABEL.match(lines[k]))
            if empty:
                i = k
                continue
        out.append(lines[i])
        i += 1
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def _write_status(row: dict, job: Job) -> None:
    prompt = status_prompt(row["project_id"])
    job.stage("Drafting")
    found, pid = ai.structured(prompt, STATUS_SYSTEM, StatusDraft)
    body = tidy_body(found.body)
    health = (found.health or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not _row(row["id"]):
        return                                  # discarded while the AI wrote
    _set(row["id"], status="ready", body=body, health=health if health in vocab.HEALTH else None,
         why=" ".join((found.why or "").split())[:300] or None, written_by=written_by(pid), edited=0)


# A task broken down

BREAKDOWN_SYSTEM = f"""You break a task into the subtasks that would get it done, for the person doing it.

- 2 to {MAX_SUBTASKS} subtasks, in the order they'd be done. Each is a concrete step someone can start and finish,
  written as a short imperative under 12 words ("Draft the supplier email"). Don't repeat the task itself or a
  subtask it already has.
- estimate_min: a realistic estimate in minutes for that step alone (15, 30, 60, 120…). When the task has an
  estimate, the steps should roughly add up to it.
Use what the task says; where it says little, propose the usual steps for that kind of work."""


class Step(BaseModel):
    text: str
    estimate_min: int = Field(description="minutes")


class Breakdown(BaseModel):
    subtasks: list[Step]


def breakdown_prompt(item_id: str) -> str:
    item = items.get(item_id)
    lines = [f"TASK: {item['text']}"]
    if item["project_id"]:
        p = db.one("SELECT name, summary FROM tasks_projects WHERE id = ?", (item["project_id"],))
        lines.append(f"PROJECT: {p['name']}" + (f" ({p['summary']})" if p["summary"] else ""))
    if item["milestone_id"]:
        m = db.one("SELECT name FROM tasks_milestones WHERE id = ?", (item["milestone_id"],))
        lines.append(f"MILESTONE: {m['name']}")
    if item["parent_id"]:
        parent = db.one("SELECT text FROM tasks_items WHERE id = ?", (item["parent_id"],))
        lines.append(f"PART OF: {parent['text']}")
    if item["due_on"]:
        lines.append(f"DUE: {item['due_on']}")
    if item["estimate_min"]:
        lines.append(f"ESTIMATE FOR THE WHOLE TASK: {item['estimate_min']} minutes")
    if item["subtasks"]:
        lines.append("SUBTASKS IT HAS ALREADY:")
        lines += [f"- {s['text']}" for s in item["subtasks"]]
    notes = item["notes"].strip()
    if notes:
        lines += ["NOTES:", notes if len(notes) <= 3000 else notes[:3000].rstrip() + "…"]
    return "\n".join(lines)


def _estimate(value) -> int | None:
    """Minutes, rounded to a step a person would say (5 under an hour, 15 under a day, else 30); None for nonsense."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n <= 0:
        return None
    step = 5 if n < 60 else 15 if n < 480 else 30
    return min(max(step, round(n / step) * step), 40 * 60)


def _write_breakdown(row: dict, job: Job) -> None:
    prompt = breakdown_prompt(row["item_id"])
    job.stage("Breaking it down")
    found, pid = ai.structured(prompt, BREAKDOWN_SYSTEM, Breakdown)
    fresh = _row(row["id"])
    if not fresh:
        return
    kept = [p for p in json.loads(fresh["proposals"]) if p["state"] != "proposed"]
    have = {" ".join(t.casefold().split()) for t in
            [p["text"] for p in kept] + [r["text"] for r in db.query("SELECT text FROM tasks_items WHERE parent_id = ?",
                                                                     (row["item_id"],))]}
    proposals = list(kept)
    for step in found.subtasks:
        text = " ".join((step.text or "").split()).rstrip(".")[:300]
        if not text or text.casefold() in have:
            continue
        have.add(text.casefold())
        proposals.append({"id": db.new_id(), "text": text, "estimate_min": _estimate(step.estimate_min),
                          "state": "proposed", "item_id": None})
        if len(proposals) - len(kept) >= MAX_SUBTASKS:
            break
    _set(row["id"], status="ready", proposals=proposals, written_by=written_by(pid), edited=0)
