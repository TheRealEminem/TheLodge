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
