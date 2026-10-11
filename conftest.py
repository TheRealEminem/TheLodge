"""Test setup shared by core/tests and every module's tests: a throwaway data folder, the whole app loaded
once, a stand-in module for testing the host on its own, and a fake AI so nothing reaches a real model.
Tests of modules that app.json doesn't turn on are skipped."""
import json
import os
import tempfile
from pathlib import Path

import pytest

_prefix = json.loads((Path(__file__).parent / "app.json").read_text())["envPrefix"]
os.environ[f"{_prefix}_DATA_DIR"] = tempfile.mkdtemp(prefix="family-test-")
os.environ[f"{_prefix}_UI_DIR"] = "/nonexistent"

from fastapi.testclient import TestClient  # noqa: E402

from core.server import ai, config, db, jobs, module  # noqa: E402
from core.server.app import app  # noqa: E402

ENABLED = config.enabled_modules()


def pytest_ignore_collect(collection_path, config):  # noqa: A002 - pytest's name
    parts = Path(collection_path).resolve().relative_to(Path(__file__).parent).parts
    return len(parts) > 1 and parts[0] == "modules" and parts[1] not in ENABLED


# A stand-in module, so the host's own tests don't depend on which real modules this app has.
module.register(module.Module(
    id="probe",
    name="Probe",
    migrations=["CREATE TABLE probe_items (id TEXT PRIMARY KEY, title TEXT NOT NULL)"],
    describe=lambda i: (lambda row: {"title": row["title"], "href": f"#/probe/{i}"} if row else None)(
        db.one("SELECT title FROM probe_items WHERE id = ?", (i,))),
))


@pytest.fixture
def probe_item():
    """Makes a row in the stand-in module and returns its ref."""
    def make(title: str) -> str:
        item_id = db.new_id()
        db.execute("INSERT INTO probe_items (id, title) VALUES (?, ?)", (item_id, title))
        return f"probe:{item_id}"
    return make


@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture
def fake_ai(monkeypatch):
    """Replies with `fake_ai.reply` (set it in the test) and records every prompt in `fake_ai.prompts`."""
    class Fake:
        reply = "Overview.\n\n## Action items\n- [ ] Do the thing"
        prompts: list[str] = []

        def __call__(self, prompt, system=None, choice="auto"):
            self.prompts.append(prompt)
            return self.reply, "fake"

    fake = Fake()
    monkeypatch.setattr(ai, "complete", fake)
    yield fake
    jobs.drain()
