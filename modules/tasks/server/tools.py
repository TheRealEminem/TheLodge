"""What Claude may do with your work, through the host's MCP server (core/server/mcp.py): see what's on your plate,
find tasks and projects, add a task, and propose sending a task where its project is linked.

Proposing is all a tool can do about sending: it's the same request as "Send to Plane" on the task page
(synced.share), and whoever takes it waits for your approval. Nothing here approves anything, and the host refuses
to start waiting work while a tool runs.
"""
from datetime import date, timedelta

from core.server import config, db, links, people, settings
from core.server.mcp import Tool

from . import hooks, items, projects, synced, vocab

PRIORITY = {"none": 0, "low": 1, "medium": 2, "high": 3, "urgent": 4}
PRIORITY_NAMES = list(PRIORITY)
WHEN = {"late": "Late", "today": "Late and today", "week": "Late, today and the next seven days",
        "all": "Everything open", "waiting": "Waiting on others"}
GROUPS = (("late", "Late"), ("today", "Today"), ("week", "This week"), ("later", "Later"), ("no_date", "No date"))
MAX_FOUND = 50


# ── Shapes Claude reads ───────────────────────────────────────────────

def _project_names() -> dict[str, str]:
    return {r["id"]: r["name"] for r in db.query("SELECT id, name FROM tasks_projects")}


def _shown(item: dict, names: dict[str, str], linked: dict[str, dict]) -> dict:
    """A task, briefly: only what says something (no priority when it has none, no assignee when it's yours)."""
    out = {"ref": links.ref("tasks", item["id"]), "text": item["text"],
           "status": vocab.ITEM_STATUSES[item["status"]]["label"]}
    if item["priority"]:
        out["priority"] = vocab.PRIORITIES[item["priority"]]["label"]
    for key in ("due_on", "start_on"):
        if item.get(key):
            out[key] = item[key]
    if item["project_id"]:
        out["project"] = names.get(item["project_id"])
    if item["assignee_ref"] != "core:me" and (item["assignee_name"] or item["assignee_ref"]):
        out["assignee"] = item["assignee_name"] or item["assignee_ref"]
    if item.get("blocked"):
        out["blocked"] = True
    about = linked.get(item["id"])
    if about:
        out["linked"] = {"to": about["source"], "url": about["url"]}
        if about["edited"]:
            out["linked"]["changes_not_sent"] = [synced.LABELS[g] for g in about["edited"]]
        if about["conflicts"]:
            out["linked"]["changed_there_too"] = [c["label"] for c in about["conflicts"]]
        if about["removed_at"]:
            out["linked"]["removed_there"] = True
    out["href"] = hooks.ITEM_HREF.format(id=item["id"])
    return out


def _shown_all(found: list[dict]) -> list[dict]:
    names, linked = _project_names(), synced.about([i["id"] for i in found])
    return [_shown(i, names, linked) for i in found]


def _group(due: str | None, today: date) -> str:
    if not due:
        return "no_date"
    if due < today.isoformat():
        return "late"
    if due == today.isoformat():
        return "today"
    return "week" if due <= (today + timedelta(days=7)).isoformat() else "later"


def _item_id(value: str) -> str:
    item_id = (value or "").strip().removeprefix("tasks:")
    if not db.one("SELECT 1 AS x FROM tasks_items WHERE id = ?", (item_id,)):
        raise ValueError(f"There's no task {value}. Find it first with tasks_find.")
    return item_id


def _project(value: str) -> dict:
    """A project by its ref, id or name (a unique part of a name will do)."""
    wanted = value.strip().removeprefix("tasks:")
    row = db.one("SELECT id, name FROM tasks_projects WHERE id = ?", (wanted,))
    if row:
        return row
    rows = db.query("SELECT id, name FROM tasks_projects WHERE archived_at IS NULL ORDER BY sort, created_at")
    for found in ([r for r in rows if r["name"].casefold() == wanted.casefold()],
                  [r for r in rows if wanted.casefold() in r["name"].casefold()]):
        if len(found) == 1:
            return found[0]
        if found:
            raise ValueError(f"“{value}” could be {', '.join(r['name'] for r in found)}. Say which.")
    raise ValueError(f"There's no project called “{value}”. The projects are: {', '.join(r['name'] for r in rows)}."
                     if rows else "There are no projects yet.")


def _assignee(name: str) -> dict:
    """You, or someone the people directory knows, or else just a name (as the task page's picker does)."""
    name = " ".join(name.split())
    your_name = settings.section("core")["your_name"].strip()
    if name.casefold() in ("me", "myself", "i", "you") or (
            your_name and name.casefold() in (your_name.casefold(), your_name.split()[0].casefold())):
        return {"assignee_ref": "core:me", "assignee_name": your_name or None}
    found = people.find(name, 5)["people"]
    exact = [p for p in found if p["name"].casefold() == name.casefold()]
    pick = exact[0] if len(exact) == 1 else (found[0] if len(found) == 1 else None)
    if pick:
        return {"assignee_ref": pick["ref"], "assignee_name": pick["name"]}
    return {"assignee_ref": None, "assignee_name": name}


# ── The tools ─────────────────────────────────────────────────────────

def my_plate(args: dict) -> dict:
    when = args.get("when") or "week"
    today = items.today()
    if when == "waiting":
        found = items.query(when="waiting")
        groups = [{"name": "Waiting on others", "tasks": _shown_all(found)}]
    else:
        found = items.query(assignee="mine", status="open", when=None if when == "all" else when)
        shown = dict(zip((i["id"] for i in found), _shown_all(found)))
        groups = []
        for key, label in GROUPS:
            these = [shown[i["id"]] for i in found if _group(i["due_on"], today) == key]
            if these:
                groups.append({"name": label, "tasks": these})
    out = {"today": f"{today:%A} {today.isoformat()}", "showing": WHEN[when], "groups": groups,
           "counts": items.counts("mine"), "href": f"#/tasks?when={'today' if when == 'late' else when}"}
    if when != "waiting":
        out["waiting_on_others"] = len(items.query(when="waiting"))
    if not found:
        out["note"] = "Nothing here." if when == "all" else "Nothing due. when=all shows tasks with later or no dates."
    return out


def find(args: dict) -> dict:
    q, project = (args.get("q") or "").strip(), (args.get("project") or "").strip()
    if not q and not project:
        raise ValueError("Say what to look for (q), or which project (project), or both.")
    limit = max(1, min(args.get("limit") or 20, MAX_FOUND))
    where = _project(project) if project else None
    found = items.query(project=where["id"] if where else None, q=q or None,
                        status="all" if args.get("include_done") else "open", parent="any" if q else "top")
    out = {"tasks": _shown_all(found[:limit])}
    if len(found) > limit:
        out["more"] = len(found) - limit
    if q and not where:
        words = " ".join(f'"{w}"*' for w in q.replace('"', " ").split())
        ids = {r["id"] for r in db.query("SELECT id FROM tasks_fts WHERE kind = 'project' AND tasks_fts MATCH ?",
                                         (words,))}
        out["projects"] = [_project_shown(p) for p in projects.query("all") if p["id"] in ids]
    if where:
        out["project"] = _project_shown(projects.get(where["id"]))
    return out


def _project_shown(p: dict) -> dict:
    roll = p["rollup"]
    out = {"ref": links.ref("tasks", p["id"]), "name": p["name"],
           "status": vocab.PROJECT_STATUSES[p["status"]]["label"],
           "progress": f"{roll['done']} of {roll['counted']} done", "late": roll["late"]}
    if p.get("health"):
        out["health"] = vocab.HEALTH[p["health"]]["label"]
    if p.get("due_on"):
        out["due_on"] = p["due_on"]
    if p.get("summary"):
        out["summary"] = p["summary"]
    if links.targets(links.ref("tasks", p["id"]), "synced"):
        out["linked"] = True
    out["href"] = hooks.PROJECT_HREF.format(id=p["id"])
    return out


def add(args: dict) -> dict:
    fields = {"text": " ".join((args.get("text") or "").split()), "source": "ai"}
    for key in ("due_on", "start_on", "notes", "status"):
        if args.get(key):
            fields[key] = args[key]
    if args.get("priority"):
        fields["priority"] = PRIORITY[args["priority"]]
    if args.get("assignee"):
        fields.update(_assignee(args["assignee"]))
    where = _project(args["project"]) if args.get("project") else None
    item_id = items.create(fields.pop("text"), project_id=where["id"] if where else None, **fields)
    out = {"added": _shown_all([items.get(item_id)])[0]}
    if where and links.targets(links.ref("tasks", where["id"]), "synced"):
        out["note"] = (f"It's only here so far. {where['name']} is linked elsewhere, so tasks_propose_send can propose "
                       "adding it there too, for the user to approve.")
    return out


def propose_send(args: dict) -> dict:
    item_id = _item_id(args["task"])
    asked = synced.share(item_id)          # raises ValueError with why, when there's nothing to send or nowhere to
    waits = synced.sharing([item_id]).get(item_id, [])
    return {"task": _shown_all([items.get(item_id)])[0],
            "proposed": "a new item there" if asked["new"] else [synced.LABELS[g] for g in asked["fields"]],
            "waits_in": waits,
            "note": "Nothing has been sent. It waits in the app until the user reviews it and presses Send."}


TOOLS = [
    Tool(
        name="my_plate", title="What's on my plate", handler=my_plate,
        description=f"The user's open tasks in {config.NAME} (theirs, or nobody's), grouped Late, Today, This week, "
                    "Later and No date, with counts. when: week (default: late, today and the next seven days), today, "
                    "late, all (every open task, dated or not), or waiting (anything waiting on someone else). A task "
                    "linked to work kept elsewhere (a team's tracker) says where, and which changes aren't sent yet.",
        params={"when": {"type": "string", "enum": list(WHEN), "description": "Which tasks; week if left out."}},
    ),
    Tool(
        name="find", title="Find tasks and projects", handler=find,
        description="Finds tasks by words, or lists a project's tasks, or both. Open tasks only unless include_done. "
                    "Words also find projects (with progress). A project can be named, or given by its ref.",
        params={"q": {"type": "string", "description": "Words to look for."},
                "project": {"type": "string", "description": "A project's name (part of it will do) or ref."},
                "include_done": {"type": "boolean", "description": "Include done and dropped tasks."},
                "limit": {"type": "integer", "description": f"At most this many tasks (20 if left out, {MAX_FOUND} at most)."}},
    ),
    Tool(
        name="add", title="Add a task", handler=add, writes=True,
        description=f"Adds one task to {config.NAME}, straight away. For follow-ups found in a thread, an email or "
                    "meeting notes, put the text in the inbox instead (inbox_capture, when the app has an inbox), so "
                    "the user reviews them first. The task stays here: nothing is sent anywhere else (see "
                    "tasks_propose_send).",
        params={"text": {"type": "string", "description": "The task, as a short imperative."},
                "project": {"type": "string", "description": "A project's name (part of it will do) or ref."},
                "due_on": {"type": "string", "description": "YYYY-MM-DD."},
                "start_on": {"type": "string", "description": "YYYY-MM-DD."},
                "priority": {"type": "string", "enum": PRIORITY_NAMES},
                "assignee": {"type": "string", "description": "Who will do it: me, or a person's name."},
                "status": {"type": "string", "enum": list(vocab.OPEN)},
                "notes": {"type": "string", "description": "Markdown."}},
        required=("text",),
    ),
    Tool(
        name="propose_send", title="Propose sending a task", handler=propose_send, writes=True,
        description="Proposes sending a task's changes to where its project is linked (a team's tracker), or adding "
                    "it there when it isn't there yet. Only proposes: it waits in the app with a preview, field by "
                    "field, until the user reviews it and presses Send. Nothing is sent by this tool.",
        params={"task": {"type": "string", "description": "The task's ref (tasks:…), from my_plate or find."}},
        required=("task",),
    ),
]
