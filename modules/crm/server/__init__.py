"""People: the relationship CRM. Who you know, how well, and what you know about them, kept as a graph of
people, organizations, meetings, documents and topics.

Everything is a node (crm_entities) or an edge (crm_relationships). See store.py for the tables.
"""
from core.server import jobs, schedule
from core.server.module import Module

from . import calendar_sync, exporting, granola, ingest, roles, routes, store

def on_settings_changed(payload: dict) -> None:
    """Pasting a key or an address is the cue to try it, so the first sync doesn't wait for its turn."""
    ingest.on_settings_changed(payload)
    keys = payload.get("keys", [])
    if "crm.granola_api_key" in keys and granola.configured():
        jobs.enqueue("crm", "granola_sync", schedule.TARGET)
    if "crm.calendar_secret" in keys and calendar_sync.configured():
        jobs.enqueue("crm", "calendar_sync", schedule.TARGET)


MODULE = Module(
    id="crm",
    name="People",
    router=routes.router,
    migrations=store.MIGRATIONS,
    settings={**roles.SETTINGS, "webhook_auto_apply": False, "granola_api_key": "", "granola_auto_apply": True,
              "granola_days": 30, "calendar_secret": ""},
    choices=roles.CHOICES,
    jobs={"extract": ingest.handle_extract, "granola_sync": granola.handle_sync, "calendar_sync": calendar_sync.handle_sync},
    lanes={"extract": ingest.lane, "granola_sync": "cloud", "calendar_sync": "cloud"},
    recurring={"granola_sync": granola.seconds, "calendar_sync": calendar_sync.seconds},
    subscribe={"core.settings.changed": on_settings_changed, "core.restored": exporting.on_restored},
    export=exporting.export,
    search=store.search,
    describe=store.describe,
)
