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


def test_the_app_is_busy_while_a_job_runs_but_not_while_one_waits_for_you(client):
    import threading

    started, release = threading.Event(), threading.Event()
    jobs.register("testmod", "long", lambda job: (started.set(), release.wait(10)))
    jobs.register("testmod", "asks", lambda job: None)
    jobs.enqueue("testmod", "asks", "t5", approve=True)
    jobs.drain()
    assert client.get("/api/jobs/busy").json() == {"busy": False}  # parked for you isn't busy
    jobs.enqueue("testmod", "long", "t4")
    assert started.wait(5)
    assert client.get("/api/jobs/busy").json() == {"busy": True}
    release.set()
    jobs.drain()
    assert client.get("/api/jobs/busy").json() == {"busy": False}


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


def test_cloud_jobs_run_side_by_side_and_everything_else_one_at_a_time():
    import threading

    together = threading.Barrier(3, timeout=5)   # three cloud jobs must be running at once to get past this
    jobs.register("testmod", "web", lambda job: together.wait(), lane="cloud")
    for i in range(3):
        jobs.enqueue("testmod", "web", f"w{i}")
    jobs.drain()
    assert all(jobs.latest("testmod", [f"w{i}"])[f"w{i}"]["status"] == "done" for i in range(3))

    running, most = 0, 0
    lock = threading.Lock()

    def local(job):
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        threading.Event().wait(0.05)
        with lock:
            running -= 1

    jobs.register("testmod", "here", local)
    for i in range(4):
        jobs.enqueue("testmod", "here", f"h{i}")
    jobs.drain()
    assert most == 1


def test_a_jobs_lane_can_depend_on_what_it_is_about():
    import threading

    names = []
    jobs.register("testmod", "picky", lambda job: names.append(threading.current_thread().name),
                  lane=lambda target: "cloud" if target.startswith("c") else "default")
    jobs.enqueue("testmod", "picky", "cloudy")
    jobs.enqueue("testmod", "picky", "local")
    jobs.drain()
    assert sorted(n.rsplit("_", 1)[0] for n in names) == ["jobs-cloud", "jobs-default"]


def test_waiting_jobs_of_a_kind_can_be_listed_to_resume_them_all():
    def parked(job):
        if not job.forced:
            raise jobs.Wait("Out of credit")

    jobs.register("testmod", "parks", parked)
    ids = [jobs.enqueue("testmod", "parks", f"p{i}") for i in range(2)]
    jobs.drain()
    assert sorted(jobs.waiting("testmod", "parks")) == sorted(ids)
    for job_id in jobs.waiting("testmod", "parks"):
        jobs.go(job_id, force=True)
    jobs.drain()
    assert jobs.waiting("testmod", "parks") == []


def test_the_data_folder_and_database_are_readable_only_by_you():
    import stat

    assert stat.S_IMODE(config.DATA_DIR.stat().st_mode) == 0o700
    assert stat.S_IMODE(db.DB_PATH.stat().st_mode) == 0o600


# ── Recurring work ────────────────────────────────────────────────────

def test_recurring_work_is_queued_when_due_and_leaves_one_row():
    from core.server import schedule

    schedule.reset()
    ran = []
    jobs.register("testmod", "tidy", lambda job: ran.append(job.target))
    schedule.register("testmod", "tidy", 900)
    assert schedule.tick(now=1000.0) == ["testmod/tidy"]       # nothing has run yet, so it's due
    jobs.drain()
    assert schedule.tick(now=1100.0) == []                      # 100 s later: not yet
    assert schedule.tick(now=1901.0) == ["testmod/tidy"]
    jobs.drain()
    assert ran == ["scheduled", "scheduled"]
    assert db.one("SELECT count(*) AS n FROM core_jobs WHERE module = 'testmod' AND kind = 'tidy'")["n"] == 1


def test_recurring_work_that_is_paused_is_not_queued_and_picks_up_when_it_is_not():
    from core.server import schedule

    schedule.reset()
    on = {"seconds": 0}
    jobs.register("testmod", "tidy", lambda job: None)
    schedule.register("testmod", "tidy", lambda: on["seconds"])
    assert schedule.tick(now=5000.0) == []
    on["seconds"] = 60
    assert schedule.tick(now=5001.0) == ["testmod/tidy"]


def test_a_module_lists_its_recurring_work_and_the_host_wires_it():
    from core.server import module, schedule

    schedule.reset()
    module.register(module.Module(id="testmod2", name="Test", jobs={"poll": lambda job: None}, recurring={"poll": 300}))
    assert schedule.tick(now=9000.0) == ["testmod2/poll"]
    jobs.drain()


def test_tags_are_normalized_the_same_way_everywhere():
    from core.server.tags import normalize_tags
    assert normalize_tags(["Angel Investor", " angel  investor ", "", "Climate"]) == ["angel-investor", "climate"]
