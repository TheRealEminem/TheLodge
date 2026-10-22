import datetime

import pytest

from core.server import db
from modules.tasks.server import items

TODAY = datetime.date(2026, 10, 19)


@pytest.fixture(autouse=True)
def clean_tasks(monkeypatch):
    """Every test starts with no projects or tasks, and a fixed "today" (Monday 19 October 2026)."""
    def wipe():
        for table in ("tasks_synced", "tasks_blockers", "tasks_updates", "tasks_items", "tasks_milestones", "tasks_projects", "tasks_fts"):
            db.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM core_links WHERE from_ref LIKE 'tasks:%' OR to_ref LIKE 'tasks:%'")
    wipe()
    monkeypatch.setattr(items, "today", lambda: TODAY)
    yield
    wipe()
