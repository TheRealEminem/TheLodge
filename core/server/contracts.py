"""Shared events: the agreements that let modules work together without knowing about each other.

Any module may publish these and any module may listen. Add a contract here when a second module needs to
react to the same kind of thing; keep a module's private events ("notes.note.saved") in the module.
Payloads are plain dicts; the TypedDicts document their shape.
"""
from typing import TypedDict

# Something produced action items (a summarized note, a meeting…). The tasks module turns them into tasks.
ACTIONS_FOUND = "actions.found"


class ActionsFound(TypedDict):
    source_ref: str          # "<module>:<id>" of where they came from
    items: list[str]         # each item's text, in order


# Something was deleted: modules holding links or copies that point at it can clean up.
ITEM_DELETED = "item.deleted"


class ItemDeleted(TypedDict):
    ref: str


# ── Work kept somewhere else too ───────────────────────────────────────
# Work that also lives in another system (a Plane work item…). The module that talks to that system (plane) maps
# its fields to the names below and publishes these; the module holding the local copy (tasks) keeps the values both
# sides last agreed on (the "base"), follows changes to fields you haven't touched, and flags the ones you have.
# Neither knows the other: a future Linear or GitHub Issues module could publish the same.

WORK_FIELDS = ("text", "notes", "status", "priority", "start_on", "due_on", "assignee_ref", "assignee_name")

# A project elsewhere should have a local project: make one and link it ("tasks:<id>" → ref, kind "synced").
WORK_PROJECT_ARRIVED = "work.project_arrived"


class WorkProjectArrived(TypedDict):
    ref: str                 # "<module>:<id>" of the project elsewhere ("plane:<project id>")
    name: str
    summary: str | None
    source: str              # where it lives, for the screen ("Plane")


# Something elsewhere should become a local, linked copy ("Bring into Traverse"). It goes into the local project
# synced with project_ref, and is linked "tasks:<id>" → ref, kind "synced". Arriving again is an update.
WORK_ARRIVED = "work.arrived"


class WorkArrived(TypedDict):
    ref: str                 # "<module>:<id>" of the item elsewhere ("plane:<work item id>")
    fields: dict             # its values, named as in WORK_FIELDS
    project_ref: str | None  # the project it's in there
    source: str              # "Plane"
    url: str | None          # where it opens there


# A linked item's values elsewhere, after they may have changed. Fields you haven't changed locally follow; fields
# changed on both sides are flagged ("Changed in Plane") until you choose. It also means the item exists again.
WORK_UPDATED_ELSEWHERE = "work.updated_elsewhere"


class WorkUpdatedElsewhere(TypedDict):
    ref: str
    fields: dict             # all of WORK_FIELDS, as they are there now
    source: str
    url: str | None


# A linked item is gone from there (deleted, or out of what's read). The local copy stays, marked.
WORK_REMOVED_ELSEWHERE = "work.removed_elsewhere"


class WorkRemovedElsewhere(TypedDict):
    ref: str
    source: str
