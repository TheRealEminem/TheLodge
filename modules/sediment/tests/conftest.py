import pytest

from core.server import db, jobs, settings


@pytest.fixture(autouse=True)
def clean_sediment():
    """Every test starts with an empty book (People's tables, through SQL, as test setup only), no subjects or
    readings, no queued work, and Sediment's default settings."""
    jobs.drain()
    for table in ("sediment_messages", "sediment_conversations", "sediment_portraits", "sediment_readings", "sediment_subjects", "crm_relationships", "crm_notes", "crm_fts", "crm_entities"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM core_jobs WHERE module IN ('sediment', 'crm')")
    settings.update({"sediment.reading_provider": "auto", "sediment.talk_provider": "auto", "sediment.transcripts": True})
    yield
    jobs.drain()
