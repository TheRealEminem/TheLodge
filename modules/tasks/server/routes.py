"""The tasks API, mounted at /api/tasks (the Lodge blueprint §9). Fixed paths come before /{task_id}.

Errors are a sentence a person can read: 400 for a value that isn't right, 404 for something that isn't there.
Creates answer 201 with {id}; deletes answer 204. PATCH /api/tasks/{id} with {done} keeps working as before.
"""
from contextlib import contextmanager

from fastapi import APIRouter, Body, HTTPException

from core.server import links, module

from . import items, projects, synced, vocab

router = APIRouter()

ITEM_FIELDS = {"text", "project_id", "milestone_id", "parent_id", "status", "notes", "priority", "start_on", "due_on",
               "assignee_ref", "assignee_name", "estimate_min", "tags", "attributes"}
PROJECT_FIELDS = {"name", "summary", "brief", "status", "health", "start_on", "due_on", "owner_ref", "owner_name",
                  "tags", "attributes"}


@contextmanager
def answers(missing: str = "Task not found"):
    try:
        yield
    except KeyError as e:
        raise HTTPException(404, missing) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


def _only(body: dict, allowed: set[str]) -> dict:
    unknown = set(body) - allowed
    if unknown:
        raise HTTPException(400, f"Can't set {', '.join(sorted(unknown))}")
    return body


def _with_source(item: dict, linked: dict | None = None) -> dict:
    """An item, with where it came from (came_from) described by that module: None if it's gone or its module is
    off. ("source" stays the item's kind of source: manual, action-item, ai, import, linked.) A linked item also
    says what it's linked to and what's waiting for a choice (synced), from `linked` when the caller looked it up
    for a whole list."""
    if linked is None:
        linked = synced.about([item["id"]])
    about = linked.get(item["id"])
    if about:
        there = module.describe(about["ref"])
        about = {**about, "title": there["title"] if there else None}
    return {**item, "came_from": module.describe(item["source_ref"]) if item.get("source_ref") else None,
            "synced": about}


def _with_sources(found: list[dict]) -> list[dict]:
    linked = synced.about([i["id"] for i in found])
    return [_with_source(i, linked) for i in found]


# ── Fixed paths ───────────────────────────────────────────────────────

@router.get("")
def list_items(project: str | None = None, assignee: str | None = None, status: str | None = None,
               when: str | None = None, q: str | None = None, parent: str | None = "top"):
    with answers():
        return _with_sources(items.query(project=project, assignee=assignee, status=status, when=when, q=q,
                                         parent=parent))


@router.get("/count")
def count(assignee: str | None = None):
    return items.counts(assignee)


@router.get("/meta")
def meta():
    return vocab.meta()


@router.post("", status_code=201)
def create_item(body: dict = Body(...)):
    fields = dict(_only(body, ITEM_FIELDS))
    with answers():
        return {"id": items.create(fields.pop("text", ""), **fields)}


@router.get("/projects")
def list_projects(status: str | None = None, archived: bool = False):
    with answers():
        return [{**p, "synced_with": _synced_with(links.ref("tasks", p["id"]))} for p in projects.query(status, archived)]


@router.post("/projects", status_code=201)
def create_project(body: dict = Body(...)):
    fields = dict(_only(body, PROJECT_FIELDS))
    with answers():
        return {"id": projects.create(fields.pop("name", ""), **fields)}


@router.get("/projects/{project_id}")
def get_project(project_id: str):
    project = projects.get(project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    return {**project, "synced_with": _synced_with(links.ref("tasks", project_id))}


def _synced_with(ref: str) -> list[dict]:
    """What a project is kept in step with elsewhere (a Plane project), each described by its own module."""
    return [d for d in (module.describe(r) for r in links.targets(ref, "synced")) if d]


@router.patch("/projects/{project_id}")
def patch_project(project_id: str, body: dict = Body(...)):
    with answers("Project not found"):
        return projects.update(project_id, body)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str):
    if not projects.delete(project_id):
        raise HTTPException(404, "Project not found")


@router.post("/projects/{project_id}/move")
def move_project(project_id: str, body: dict = Body(...)):
    with answers("Project not found"):
        return projects.move(project_id, body.get("after_id"))


@router.post("/projects/{project_id}/milestones", status_code=201)
def add_milestone(project_id: str, body: dict = Body(...)):
    with answers("Project not found"):
        return projects.add_milestone(project_id, body.get("name", ""), body.get("due_on"))


@router.get("/projects/{project_id}/updates")
def project_updates(project_id: str):
    if projects.get(project_id) is None:
        raise HTTPException(404, "Project not found")
    return projects.updates(project_id)


@router.post("/projects/{project_id}/updates", status_code=201)
def add_project_update(project_id: str, body: dict = Body(...)):
    _only(body, {"kind", "body", "health"})
    with answers("Project not found"):
        return projects.add_update(project_id=project_id, kind=body.get("kind", "comment"), body=body.get("body", ""),
                                   health=body.get("health"))


@router.patch("/milestones/{milestone_id}")
def patch_milestone(milestone_id: str, body: dict = Body(...)):
    with answers("Milestone not found"):
        return projects.update_milestone(milestone_id, body)


@router.delete("/milestones/{milestone_id}", status_code=204)
def delete_milestone(milestone_id: str):
    if not projects.delete_milestone(milestone_id):
        raise HTTPException(404, "Milestone not found")


# ── One item ──────────────────────────────────────────────────────────

@router.get("/{task_id}")
def get_item(task_id: str):
    item = items.get(task_id)
    if item is None:
        raise HTTPException(404, "Task not found")
    return _with_source(item)


@router.patch("/{task_id}")
def patch_item(task_id: str, body: dict = Body(...)):
    with answers():
        return _with_source(items.update(task_id, body))


@router.delete("/{task_id}", status_code=204)
def delete_item(task_id: str):
    if not items.delete(task_id):
        raise HTTPException(404, "Task not found")


@router.post("/{task_id}/move")
def move_item(task_id: str, body: dict = Body(...)):
    _only(body, {"project_id", "milestone_id", "after_id", "within", "status"})
    with answers():
        return _with_source(items.move(task_id, project_id=body.get("project_id"), milestone_id=body.get("milestone_id"),
                                       after_id=body.get("after_id"), within=body.get("within", "milestone"),
                                       status=body.get("status")))


@router.post("/{task_id}/synced")
def resolve_synced(task_id: str, body: dict = Body(...)):
    """A field changed both here and there: {"field": "due_on", "keep": "theirs" | "mine"}."""
    _only(body, {"field", "keep"})
    with answers("That task isn't linked"):
        return _with_source(synced.resolve(task_id, body.get("field", ""), body.get("keep", "")))


@router.delete("/{task_id}/synced")
def unlink_synced(task_id: str):
    """Stops following the other side; the task stays, as your own."""
    if not synced.unlink(task_id):
        raise HTTPException(404, "That task isn't linked")
    return _with_source(items.get(task_id))


@router.post("/{task_id}/blockers")
def add_blocker(task_id: str, body: dict = Body(...)):
    if not body.get("blocked_by"):
        raise HTTPException(400, "Say which task it waits on (blocked_by)")
    with answers():
        return _with_source(items.block(task_id, body.get("blocked_by", "")))


@router.delete("/{task_id}/blockers/{blocked_by}")
def remove_blocker(task_id: str, blocked_by: str):
    with answers():
        return _with_source(items.unblock(task_id, blocked_by))


@router.post("/{task_id}/updates", status_code=201)
def add_item_update(task_id: str, body: dict = Body(...)):
    _only(body, {"kind", "body"})
    with answers():
        return projects.add_update(item_id=task_id, kind=body.get("kind", "comment"), body=body.get("body", ""))
