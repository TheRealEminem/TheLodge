import pytest

from core.server import db, jobs, settings


@pytest.fixture(autouse=True)
def clean_crm():
    """Every test starts with an empty CRM, an empty inbox, no queued work, and the default AI choices."""
    jobs.drain()
    for table in ("crm_relationships", "crm_notes", "crm_inbox", "crm_fts", "crm_entities"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM core_jobs WHERE module = 'crm'")
    from modules.crm.server import ingest, roles, store
    ingest._down.clear()
    settings.update({f"crm.{name}": default for name, default in {**roles.SETTINGS, "webhook_auto_apply": False}.items()})
    store._touch()  # drops the matching index's cache
    yield
    jobs.drain()
