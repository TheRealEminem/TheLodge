"""Test setup shared by core/tests and every module's tests: a throwaway data folder and family folder, the whole
app loaded once, a stand-in module for testing the host on its own, and a fake AI so nothing reaches a real model.
Tests of modules that app.json doesn't turn on are skipped."""
import json
import os
import tempfile
from pathlib import Path

import pytest

_prefix = json.loads((Path(__file__).parent / "app.json").read_text())["envPrefix"]
os.environ[f"{_prefix}_DATA_DIR"] = tempfile.mkdtemp(prefix="family-test-")
os.environ[f"{_prefix}_UI_DIR"] = "/nonexistent"
os.environ["TRAILMIX_FAMILY_DIR"] = tempfile.mkdtemp(prefix="family-link-test-")   # never the Mac's real family folder
# Nothing the shell sets up for AI reaches the tests: a real key would make a provider look ready, and a base address
# would send the SDK somewhere else.
for _name in [n for n in os.environ if n.startswith((f"{_prefix}_AI_", "APP_AI_"))] + [
        "ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "OPENAI_API_KEY", "OPENAI_BASE_URL", "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY", "OLLAMA_URL", "OLLAMA_MODEL"]:
    os.environ.pop(_name, None)
# A model server running on this machine isn't reached either: a job a test leaves queued would wait on a real model
# (and out-wait jobs.drain). Nothing listens on this port, so "Ollama isn't reachable" comes back at once, as on CI.
os.environ["OLLAMA_URL"] = "http://127.0.0.1:9"

from fastapi.testclient import TestClient  # noqa: E402

from core.server import ai, config, db, jobs, lockdown, module, settings  # noqa: E402
from core.server.app import app  # noqa: E402

ENABLED = config.enabled_modules()


def pytest_ignore_collect(collection_path, config):  # noqa: A002 - pytest's name
    try:
        parts = Path(collection_path).resolve().relative_to(Path(__file__).resolve().parent).parts
    except ValueError:                  # a link to somewhere outside the app (node_modules in a worktree): not tests
        return True
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
def lockdown_on():
    """Lockdown on for one test (here and in the test family folder), then off, with any work it parked forgotten
    rather than run after the test's own fixtures are gone. A test that wants parked work to go turns it off itself."""
    settings.update({lockdown.KEY: True})
    yield
    jobs.drain()
    db.execute("DELETE FROM core_jobs WHERE status = 'waiting' AND wait_reason LIKE ?", (lockdown.REASON + "%",))
    settings.update({lockdown.KEY: False})      # after the delete: turning it off is what sends parked work on its way


@pytest.fixture
def fake_ai(monkeypatch):
    """Replies with `fake_ai.reply` (set it in the test) and records every prompt in `fake_ai.prompts`. Each call is
    counted in the usage log like a real one, as `fake_ai.tokens` (input, output) from a provider with no price."""
    class Fake:
        reply = "Overview.\n\n## Action items\n- [ ] Do the thing"
        prompts: list[str] = []
        tokens = (1200, 300)

        def __call__(self, prompt, system=None, choice="auto", purpose=None, models=None):
            self.prompts.append(prompt)

            def answer(pid, meter):
                meter.add(*self.tokens)
                return self.reply
            return ai.attempt("fake", {}, "complete", answer), "fake"

    fake = Fake()
    monkeypatch.setattr(ai, "complete", fake)
    yield fake
    jobs.drain()


@pytest.fixture
def fake_structured(monkeypatch):
    """Stands in for ai.structured. Set `.reply` to an object of the schema asked for, an exception to raise, or a
    function (prompt, system, schema) -> either. `.calls` records every call. Each is counted in the usage log as a
    call to Claude's model in Settings that used `.tokens` (input, output); an exception, as a failure with none."""
    class Fake:
        reply: object = None
        tokens = (2000, 400)

        def __init__(self):
            self.calls: list[dict] = []

        def __call__(self, prompt, system, schema, choice="auto", max_tokens=None, purpose=None, models=None):
            self.calls.append({"prompt": prompt, "system": system, "schema": schema, "choice": choice})

            def answer(pid, meter):
                reply = self.reply(prompt, system, schema) if callable(self.reply) else self.reply
                if isinstance(reply, Exception):
                    raise reply
                meter.add(*self.tokens)
                assert isinstance(reply, schema), f"the test's reply is a {type(reply).__name__}, not a {schema.__name__}"
                return reply
            return ai.attempt("anthropic", settings.section("ai"), "structured", answer), "anthropic"

    fake = Fake()
    monkeypatch.setattr(ai, "structured", fake)
    yield fake
    jobs.drain()
