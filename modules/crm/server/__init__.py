"""People: the relationship CRM. Who you know, how well, and what you know about them, kept as a graph of
people, organizations, meetings, documents and topics.

Everything is a node (crm_entities) or an edge (crm_relationships). See store.py for the tables.
"""
from core.server import jobs, schedule
from core.server.module import Module

from . import calendar_sync, duplicates, exporting, gemini_research, granola, ingest, profiles, roles, routes, sheet_sync, store

def on_settings_changed(payload: dict) -> None:
    """Pasting a key or an address is the cue to try it, so the first sync doesn't wait for its turn."""
    ingest.on_settings_changed(payload)
    keys = payload.get("keys", [])
    if "crm.granola_api_key" in keys and granola.configured():
        jobs.enqueue("crm", "granola_sync", schedule.TARGET)
    if "crm.calendar_secret" in keys and calendar_sync.configured():
        jobs.enqueue("crm", "calendar_sync", schedule.TARGET)
    if "crm.sheet_secret" in keys and sheet_sync.configured():
        jobs.enqueue("crm", "sheet_sync", schedule.TARGET)


MODULE = Module(
    id="crm",
    name="People",
    router=routes.router,
    migrations=store.MIGRATIONS,
    settings={**roles.SETTINGS, "webhook_auto_apply": False, "granola_api_key": "", "granola_auto_apply": True,
              "granola_days": 30, "calendar_secret": "", "sheet_secret": "", "overviews_ahead": True,
              "research_level": "quick", "research_batch": True, "research_budget": 5},
    choices={**roles.CHOICES, "research_level": tuple(gemini_research.LEVELS)},
    jobs={"extract": ingest.handle_extract, "granola_sync": granola.handle_sync, "calendar_sync": calendar_sync.handle_sync,
          "overview": profiles.write_overview, "overview_now": profiles.write_overview, "answer": profiles.answer,
          "overview_sweep": profiles.sweep, "sheet_sync": sheet_sync.handle_sync,
          "duplicates_check": duplicates.handle_check, "research_advance": gemini_research.handle_advance},
    lanes={"extract": ingest.lane, "granola_sync": "cloud", "calendar_sync": "cloud",
           "overview": profiles.overview_lane, "overview_now": "interactive", "answer": "interactive", "overview_sweep": "cloud",
           "sheet_sync": "cloud", "duplicates_check": "cloud", "research_advance": "cloud"},
    recurring={"granola_sync": granola.seconds, "calendar_sync": calendar_sync.seconds, "overview_sweep": profiles.sweep_seconds,
               "sheet_sync": sheet_sync.seconds, "duplicates_check": duplicates.seconds,
               "research_advance": gemini_research.seconds},
    subscribe={"core.settings.changed": on_settings_changed, "core.restored": exporting.on_restored},
    export=exporting.export,
    count=exporting.count,
    search=store.search,
    describe=store.describe,
)
