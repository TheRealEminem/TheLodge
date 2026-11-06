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
# With local_ref, it's something that was made there from here (WORK_SHARE_REQUESTED for a new one): the local thing
# becomes the linked copy, with these values as both sides' starting point, instead of a new copy being made.
WORK_ARRIVED = "work.arrived"


class WorkArrived(TypedDict, total=False):
    ref: str                 # "<module>:<id>" of the item elsewhere ("plane:<work item id>")
    fields: dict             # its values, named as in WORK_FIELDS
    project_ref: str | None  # the project it's in there
    source: str              # "Plane"
    url: str | None          # where it opens there
    local_ref: str           # optional: the local thing it was made from ("tasks:<id>")


# A linked item's values elsewhere, after they may have changed. Fields you haven't changed locally follow; fields
# changed on both sides are flagged ("Changed in Plane") until you choose. It also means the item exists again.
# take: fields you chose there to take from there even though you'd changed them here (a push stopped because
# both sides changed, and you picked theirs), so they follow anyway.
WORK_UPDATED_ELSEWHERE = "work.updated_elsewhere"


class WorkUpdatedElsewhere(TypedDict, total=False):
    ref: str
    fields: dict             # all of WORK_FIELDS, as they are there now
    source: str
    url: str | None
    take: list[str]          # optional: WORK_FIELDS names to take from there whatever you've done here


# You asked to send your changes to where a linked item also lives ("Send to Plane"). Only the fields you've changed
# since the base go, with their base values, so the other side can check nobody changed them there meanwhile and
# never write anything else. Whoever keeps that side parks the request for your approval (nothing is sent without
# it) and, while it waits, links local_ref → its waiting request (kind "share"), so the local side can show where it
# waits. Once sent, the result comes back as WORK_UPDATED_ELSEWHERE (or WORK_ARRIVED with local_ref, for a new one).
# A local thing that isn't linked yet, in a project that is, asks to be made there: ref is then local_ref itself,
# fields hold all its values and base is empty.
WORK_SHARE_REQUESTED = "work.share_requested"


class WorkShareRequested(TypedDict):
    ref: str                 # the item elsewhere ("plane:<work item id>"); for a new one, the local thing
    local_ref: str           # the local copy ("tasks:<id>")
    fields: dict             # only the changed fields, named as in WORK_FIELDS (a new one: all of them)
    base: dict               # those fields as both sides last agreed ({} for a new one)
    project_ref: str | None  # the local project ("tasks:<project id>"): where a new one goes, through its link


# New open work turned up in a local project that's linked somewhere (made there, accepted from the inbox, or moved
# in), and isn't linked itself. Nobody asked to send it: whoever keeps that side ignores it, unless you've told it to
# send a project's new work on its own (an "auto-send" switch, off by default). Then it treats this as
# WORK_SHARE_REQUESTED for a new one, which has the same shape. Rules still hold: only new work, never a delete.
WORK_ADDED = "work.added"


# Someone ticked (or unticked) a piece of work outside the module it belongs to: a pick in the day's plan. The module
# whose ref it is marks it done or open again; anything else ignores it. Work kept somewhere else too changes only
# here: it reaches the other side, like any change, only when you send it.
WORK_MARKED_DONE = "work.marked_done"


class WorkMarkedDone(TypedDict):
    ref: str                 # "<module>:<id>" of the work
    done: bool


# You asked for words of yours (a comment, a status update) to be added where a linked item also lives, as a new
# comment on it. Append only: the other side adds a comment, and never edits or deletes one, its own or anyone's.
# Whoever keeps that side parks the request for your approval with a preview (nothing is sent without it) and, while
# it waits, links update_ref → its waiting request (kind "share"); once it's there, update_ref → the sent request
# (kind "posted"). The local side shows each by describing that ref. Asking again while one waits replaces its words.
WORK_COMMENT_REQUESTED = "work.comment_requested"


class WorkCommentRequested(TypedDict):
    ref: str                 # the item elsewhere ("plane:<work item id>")
    local_ref: str           # its local copy ("tasks:<id>")
    update_ref: str          # the words being added ("tasks:<update id>")
    body: str                # markdown
    written_by: str | None   # the AI that drafted it, if one did: said with the comment there too


# A linked item is gone from there (deleted, or out of what's read). The local copy stays, marked.
WORK_REMOVED_ELSEWHERE = "work.removed_elsewhere"


class WorkRemovedElsewhere(TypedDict):
    ref: str
    source: str
