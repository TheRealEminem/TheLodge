import pytest

from core.server import db, jobs, settings


@pytest.fixture(autouse=True)
def clean_crm():
    """Every test starts with an empty CRM, an empty inbox, no queued work, and the default AI choices."""
    jobs.drain()
    for table in ("crm_relationships", "crm_notes", "crm_inbox", "crm_fts", "crm_entities", "crm_sync", "crm_sheet_rows",
                  "crm_presets", "crm_preset_asks"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM core_jobs WHERE module = 'crm'")
    from modules.crm.server import ingest, roles, store
    ingest._down.clear()
    # Most tests are about reading with a cloud AI (a fake one), so those two start on the providers they used to default to;
    # test_local_path.py is about what "auto" does.
    settings.update({f"crm.{name}": default for name, default in {**roles.SETTINGS, "extraction_provider": "anthropic", "utility_provider": "gemini",
                                                                              "webhook_auto_apply": False, "granola_api_key": "", "granola_auto_apply": True,
                                                                              "granola_days": 30, "calendar_secret": "", "sheet_secret": "", "overviews_ahead": True,
                                                                              "gravatar": False}.items()})
    store._touch()  # drops the matching index's cache
    yield
    jobs.drain()
