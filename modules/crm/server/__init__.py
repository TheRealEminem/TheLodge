"""People: the relationship CRM. Who you know, how well, and what you know about them, kept as a graph of
people, organizations, meetings, documents and topics.

Everything is a node (crm_entities) or an edge (crm_relationships). See store.py for the tables.
"""
from core.server import jobs, schedule
from core.server.module import Module

from . import calendar_sync, capture, cli_research, dossier, duplicates, exporting, gemini_research, granola, ingest, pictures, presets, profiles, roles, roundups, routes, sheet_sync, store, trailmix

def on_settings_changed(payload: dict) -> None:
    """Pasting a key or an address is the cue to try it, so the first sync doesn't wait for its turn."""
    ingest.on_settings_changed(payload)
    keys = payload.get("keys", [])
    if "crm.granola_api_key" in keys and granola.configured():
        jobs.enqueue("crm", "granola_sync", schedule.TARGET)
    if "crm.trailmix_days" in keys:
        capture.set_state("trailmix", window_from=None)   # how far back is worked out again at the next run
    if {"crm.trailmix_sync", "crm.trailmix_url", "crm.trailmix_days", "crm.trailmix_skip_workspaces"} & set(keys) and trailmix.configured():
        jobs.enqueue("crm", "trailmix_sync", schedule.TARGET)
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
              "research_level": "better", "research_via": "api", "research_batch": True, "research_budget": 5,
              "research_deep_via": "claude", "research_auto_add": True, "research_depth": "standard",
              "research_when": "now", "research_night_from": 1, "research_night_to": 6,
              "trailmix_sync": False, "trailmix_url": "http://127.0.0.1:8765", "trailmix_days": 90,
              "trailmix_auto_apply": True, "trailmix_skip_workspaces": [],
              "research_ask_model": "", "research_write_model": "", "gravatar": False},
    choices={**roles.CHOICES, "research_level": tuple(gemini_research.LEVELS),
             "research_via": ("api", *cli_research.TOOLS), "research_deep_via": tuple(cli_research.TOOLS),
             "research_depth": tuple(cli_research.DEPTHS), "research_when": ("now", "night")},
    jobs={"extract": ingest.handle_extract, "granola_sync": granola.handle_sync, "calendar_sync": calendar_sync.handle_sync,
          "overview": profiles.write_overview, "overview_now": profiles.write_overview, "answer": profiles.answer,
          "overview_sweep": profiles.sweep, "sheet_sync": sheet_sync.handle_sync,
          "duplicates_check": duplicates.handle_check, "research_advance": gemini_research.handle_advance,
          "research_cli": cli_research.handle, "trailmix_sync": trailmix.handle_sync,
          "write_presets": presets.write, "pictures_lookup": pictures.handle_lookup, "roundup": roundups.handle},
    lanes={"extract": ingest.lane, "granola_sync": "cloud", "calendar_sync": "cloud", "trailmix_sync": "cloud",
           "overview": profiles.overview_lane, "overview_now": "interactive", "answer": "interactive", "overview_sweep": "cloud",
           "sheet_sync": "cloud", "duplicates_check": "cloud", "research_advance": "cloud", "research_cli": "cloud", "write_presets": "interactive", "pictures_lookup": "cloud",
           "roundup": roundups.lane},
    recurring={"trailmix_sync": trailmix.seconds, "granola_sync": granola.seconds, "calendar_sync": calendar_sync.seconds, "overview_sweep": profiles.sweep_seconds,
               "sheet_sync": sheet_sync.seconds, "duplicates_check": duplicates.seconds,
               "research_advance": gemini_research.seconds, "research_cli": cli_research.seconds},
    subscribe={"core.settings.changed": on_settings_changed, "core.restored": exporting.on_restored},
    export=exporting.export,
    count=exporting.count,
    search=store.search,
    describe=store.describe,
    offers={dossier.OFFER: dossier.handle},
    people=dossier.people,
    ai_jobs=roles.ai_jobs(),
    startup=roles.keep_what_people_have,
)
