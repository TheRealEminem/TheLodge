import pytest

from core.server import config, db, events, jobs, links, settings


def test_app_lists_the_modules_app_json_turns_on(client):
    info = client.get("/api/app").json()
    assert [m["id"] for m in info["modules"]][: len(config.enabled_modules())] == config.enabled_modules()


def test_settings_are_namespaced_validated_and_secrets_stay_hidden(client):
    settings.declare("probe", {"enabled": False})
    assert settings.section("probe")["enabled"] is False
    r = client.put("/api/settings", json={"ai.anthropic_api_key": "sk-test-12345678"})
    assert r.status_code == 200
    body = r.json()
    assert body["values"]["ai.anthropic_api_key"] == ""
    assert body["secret_hints"]["ai.anthropic_api_key"] == "…5678"
    assert settings.section("ai")["anthropic_api_key"] == "sk-test-12345678"
    assert client.put("/api/settings", json={"ai.provider": "nope"}).status_code == 400
    assert client.put("/api/settings", json={"probe.enabled": "yes"}).status_code == 400
    assert client.put("/api/settings", json={"probe.enabled": True}).json()["values"]["probe.enabled"] is True
    assert client.put("/api/settings", json={"made.up": 1}).status_code == 400


def test_events_match_prefixes_and_survive_a_broken_handler():
    seen = []
    events.subscribe("test.*", lambda p: seen.append(p["n"]))
    events.subscribe("test.boom", lambda p: 1 / 0)
    before = events.changes(0)["seq"]
    events.publish("test.boom", {"n": 1})
    assert seen == [1]
    assert events.changes(before)["names"] == ["test.boom"]


def test_jobs_wait_for_approval_then_run():
    ran = []
    jobs.register("testmod", "work", lambda job: ran.append(job.target))
    job_id = jobs.enqueue("testmod", "work", "t1", approve=True)
    jobs.drain()
    assert ran == [] and db.one("SELECT status FROM core_jobs WHERE id = ?", (job_id,))["status"] == "waiting"
    assert jobs.enqueue("testmod", "work", "t1", approve=True) == job_id  # not doubled
    jobs.go(job_id)
    jobs.drain()
    assert ran == ["t1"]
    assert jobs.latest("testmod", ["t1"])["t1"]["status"] == "done"


def test_a_job_can_park_itself_and_be_forced_past_it():
    def careful(job):
        if not job.forced:
            raise jobs.Wait("Not enough free memory")

    jobs.register("testmod", "heavy", careful)
    job_id = jobs.enqueue("testmod", "heavy", "t2")
    jobs.drain()
    row = jobs.latest("testmod", ["t2"])["t2"]
    assert (row["status"], row["wait_reason"]) == ("waiting", "Not enough free memory")
    jobs.go(job_id, force=True)
    jobs.drain()
    assert jobs.latest("testmod", ["t2"])["t2"]["status"] == "done"


def test_failed_jobs_show_the_error_and_can_be_retried():
    attempts = []

    def flaky(job):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Ollama isn't running")

    jobs.register("testmod", "flaky", flaky)
    job_id = jobs.enqueue("testmod", "flaky", "t3")
    jobs.drain()
    assert jobs.latest("testmod", ["t3"])["t3"]["error"] == "Ollama isn't running"
    jobs.retry(job_id)
    jobs.drain()
    assert jobs.latest("testmod", ["t3"])["t3"]["status"] == "done"


def test_links_are_described_by_their_own_module(client, probe_item):
    a, b = probe_item("Trailhead"), probe_item("Summit")
    assert client.post("/api/links", json={"from_ref": a, "to_ref": b}).status_code == 201
    [other] = links.linked(b)
    assert (other["title"], other["href"], other["direction"]) == ("Trailhead", f"#/probe/{a.split(':')[1]}", "from")
    assert client.post("/api/links", json={"from_ref": "probe:missing", "to_ref": b}).status_code == 404
    links.forget(a)
    assert links.linked(b) == []


@pytest.mark.parametrize("path", ["/api/app", "/api/settings", "/api/search?q=x", "/api/links?ref=probe:x"])
def test_everything_but_sign_in_is_open_locally(client, path):
    assert client.get(path).status_code == 200
