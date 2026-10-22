"""The tasks module's vocabularies: plain strings (and one integer scale) stored in its tables, with the label and
tone each shows as. Served at GET /api/tasks/meta so the web app never hard-codes them.

Priorities follow Plane's five levels (Traverse PLAN.md D7), so nothing is lost going to and from Plane.
"""

ITEM_STATUSES = {
    "todo": {"label": "To do", "tone": "neutral"},       # not started
    "doing": {"label": "Doing", "tone": "sky"},          # someone is working on it
    "waiting": {"label": "Waiting", "tone": "berry"},    # it's with someone else
    "done": {"label": "Done", "tone": "forest"},         # finished: completed_at set, done = 1
    "dropped": {"label": "Dropped", "tone": "neutral"},  # won't happen, kept for history
}
OPEN = ("todo", "doing", "waiting")

PROJECT_STATUSES = {
    "planned": {"label": "Planned", "tone": "neutral"},
    "active": {"label": "Active", "tone": "sky"},
    "paused": {"label": "Paused", "tone": "neutral"},
    "done": {"label": "Done", "tone": "forest"},
    "dropped": {"label": "Dropped", "tone": "neutral"},
}

HEALTH = {
    "on_track": {"label": "On track", "tone": "forest"},
    "at_risk": {"label": "At risk", "tone": "sun"},
    "off_track": {"label": "Off track", "tone": "trail"},
}

PRIORITIES = {
    0: {"label": "None", "tone": "neutral"},
    1: {"label": "Low", "tone": "neutral"},
    2: {"label": "Medium", "tone": "neutral"},
    3: {"label": "High", "tone": "neutral"},
    4: {"label": "Urgent", "tone": "sun"},
}

UPDATE_KINDS = ("comment", "status", "summary")
ITEM_SOURCES = ("manual", "action-item", "ai", "import", "linked")   # linked: a copy of work kept elsewhere (synced.py)
PROJECT_SOURCES = ("manual", "ai", "import", "template")


def meta() -> dict:
    """Everything the web app needs to label and order these values."""
    def listed(d: dict) -> list[dict]:
        return [{"value": k, **v} for k, v in d.items()]
    return {"statuses": listed(ITEM_STATUSES), "open": list(OPEN), "project_statuses": listed(PROJECT_STATUSES),
            "health": listed(HEALTH), "priorities": listed(PRIORITIES), "update_kinds": list(UPDATE_KINDS)}
