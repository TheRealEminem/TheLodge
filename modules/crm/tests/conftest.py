import pytest

from core.server import db


@pytest.fixture(autouse=True)
def clean_crm():
    """Every test starts with an empty CRM."""
    for table in ("crm_relationships", "crm_notes", "crm_inbox", "crm_fts", "crm_entities"):
        db.execute(f"DELETE FROM {table}")
    from modules.crm.server import store
    store._touch()  # drops the matching index's cache
    yield
