"""Overviews of people and questions about them (profiles.py).

The AI is a fake (conftest's fake_ai), so these check what the app sends and keeps, not what a model would say."""
import pytest
from crm_helpers import link, make

from core.server import ai, db, jobs
from modules.crm.server import profiles

READY = {"provider": "ollama", "label": "Ollama", "model": "qwen", "ready": True, "reason": "", "local": True}


@pytest.fixture
def ready(monkeypatch):
    """An AI that is set up (the fake answers; this only stands in for "is a provider configured")."""
    monkeypatch.setattr(profiles, "provider", lambda: dict(READY))


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera", "title": "Founder"})
    me = client.get("/api/crm/me").json()
    priya = make(client, "person", "Priya Nair", summary="Runs pilots at Helio.",
                 attributes={"title": "CEO", "email": "priya@helio.example"})
    helio = make(client, "organization", "Helio Cold Chain")
    link(client, priya, "works_at", helio)
    client.put(f"/api/crm/people/{priya['id']}/connection", json={"strength": 4})
    client.post(f"/api/crm/entities/{priya['id']}/notes", json={"body": "Wants an intro to Frostline about the 50-truck pilot."})
    return {"me": me, "priya": priya, "bare": make(client, "person", "Jordan Reyes")}


def overview(client, person):
    r = client.get(f"/api/crm/people/{person['id']}/overview")
    assert r.status_code == 200, r.text
    return r.json()


def test_opening_a_profile_writes_its_overview_from_the_records(client, book, ready, fake_ai):
    fake_ai.reply = "Priya runs Helio.\n\n**Worth knowing**\n- Wants a Frostline intro\n\n**Next time**\nAsk about the pilot."
    first = overview(client, book["priya"])
    assert first["overview"] is None and first["job"]["kind"] == "overview_now"
    jobs.drain()
    after = overview(client, book["priya"])
    assert after["overview"]["body"].startswith("Priya runs Helio.") and after["overview"]["current"]
    prompt = fake_ai.prompts[-1]
    for fact in ("Priya Nair", "CEO at Helio Cold Chain", "Runs pilots at Helio.", "50-truck pilot",
                 "Your rating of the relationship: 4 of 5", "The owner is Alex Rivera."):
        assert fact in prompt, fact
    assert "priya@helio.example" not in prompt          # addresses stay out of what the model sees


def test_an_overview_is_written_once_and_again_when_the_records_change(client, book, ready, fake_ai):
    overview(client, book["priya"])
    jobs.drain()
    overview(client, book["priya"])
    jobs.drain()
    assert len(fake_ai.prompts) == 1                    # nothing changed, nothing written
    client.post(f"/api/crm/entities/{book['priya']['id']}/notes", json={"body": "Moved to Lisbon."})
    stale = overview(client, book["priya"])
    assert stale["overview"]["current"] is False        # the old one shows while the new one is written
    jobs.drain()
    assert len(fake_ai.prompts) == 2 and "Moved to Lisbon." in fake_ai.prompts[-1]
    assert overview(client, book["priya"])["overview"]["current"]


def test_redo_writes_it_again_even_when_nothing_changed(client, book, ready, fake_ai):
    overview(client, book["priya"])
    jobs.drain()
    client.post(f"/api/crm/people/{book['priya']['id']}/overview")
    jobs.drain()
    assert len(fake_ai.prompts) == 2


def test_no_overview_for_someone_with_nothing_on_file_or_without_an_ai(client, book, fake_ai, monkeypatch):
    monkeypatch.setattr(profiles, "provider", lambda: {**READY, "ready": False, "reason": "Add an API key"})
    state = overview(client, book["priya"])
    assert state["ready"] is False and state["reason"] == "Add an API key" and state["job"] is None
    monkeypatch.setattr(profiles, "provider", lambda: dict(READY))
    bare = overview(client, book["bare"])
    jobs.drain()
    assert bare["material"] is False and bare["job"] is None and not fake_ai.prompts


def test_a_failed_overview_is_not_retried_on_every_refresh(client, book, ready, monkeypatch):
    def broken(prompt, system=None, choice="auto", purpose=None):
        raise ai.AIError("The model refused")
    monkeypatch.setattr(ai, "complete", broken)
    overview(client, book["priya"])
    jobs.drain()
    for _ in range(3):
        state = overview(client, book["priya"])
    jobs.drain()
    assert state["job"]["status"] == "error" and "refused" in state["job"]["error"]
    assert db.one("SELECT count(*) AS n FROM core_jobs WHERE kind = 'overview_now'")["n"] == 1


def test_an_ai_that_is_down_parks_the_overview_until_it_works(client, book, ready, monkeypatch):
    def down(prompt, system=None, choice="auto", purpose=None):
        raise ai.AIError("No credit", provider_down=True)
    monkeypatch.setattr(ai, "complete", down)
    overview(client, book["priya"])
    jobs.drain()
    assert overview(client, book["priya"])["job"]["status"] == "waiting"


def test_the_sweep_writes_ahead_closest_first_a_few_at_a_time(client, book, ready, fake_ai, monkeypatch):
    monkeypatch.setitem(profiles.PER_SWEEP, "local", 1)
    close = make(client, "person", "Dana Okafor", summary="Old friend.")
    client.put(f"/api/crm/people/{close['id']}/connection", json={"strength": 5})
    profiles.sweep(jobs.Job("x", "crm", "overview_sweep", "scheduled", True, False))
    jobs.drain()
    assert [p.split("Records about ")[1].split(":")[0] for p in fake_ai.prompts] == ["Dana Okafor"]
    profiles.sweep(jobs.Job("x", "crm", "overview_sweep", "scheduled", True, False))
    jobs.drain()
    assert len(fake_ai.prompts) == 2 and "Priya Nair" in fake_ai.prompts[-1]
    profiles.sweep(jobs.Job("x", "crm", "overview_sweep", "scheduled", True, False))
    jobs.drain()
    assert len(fake_ai.prompts) == 2                    # Jordan has nothing on file; everyone else is done
    assert client.get("/api/crm/overviews").json() == {"people": 3, "written": 2}


def test_the_sweep_waits_when_switched_off_or_the_ai_is_not_set_up(client, book, fake_ai, monkeypatch):
    client.put("/api/settings", json={"crm.overviews_ahead": False})
    monkeypatch.setattr(profiles, "provider", lambda: dict(READY))
    profiles.sweep(jobs.Job("x", "crm", "overview_sweep", "scheduled", True, False))
    assert profiles.sweep_seconds() == 0
    client.put("/api/settings", json={"crm.overviews_ahead": True})
    monkeypatch.setattr(profiles, "provider", lambda: {**READY, "ready": False})
    profiles.sweep(jobs.Job("x", "crm", "overview_sweep", "scheduled", True, False))
    jobs.drain()
    assert not fake_ai.prompts


def test_asking_about_someone_keeps_the_question_and_its_answer(client, book, ready, fake_ai):
    pid = book["priya"]["id"]
    fake_ai.reply = "She wants a Frostline intro."
    r = client.post(f"/api/crm/people/{pid}/questions", json={"question": "What does she need from me?"})
    assert r.status_code == 201 and r.json()["status"] == "queued"
    jobs.drain()
    fake_ai.reply = "In the 50-truck pilot."
    client.post(f"/api/crm/people/{pid}/questions", json={"question": "Where would that help?"})
    jobs.drain()
    thread = client.get(f"/api/crm/people/{pid}/questions").json()
    assert [(q["question"], q["answer"], q["status"]) for q in thread] == [
        ("What does she need from me?", "She wants a Frostline intro.", "done"),
        ("Where would that help?", "In the 50-truck pilot.", "done")]
    follow_up = fake_ai.prompts[-1]
    assert "You asked: What does she need from me?\nAnswer: She wants a Frostline intro." in follow_up
    assert "Question: Where would that help?" in follow_up and "50-truck pilot" in follow_up
    assert client.delete(f"/api/crm/people/{pid}/questions").status_code == 204
    assert client.get(f"/api/crm/people/{pid}/questions").json() == []


def test_a_question_that_fails_says_why_and_can_be_tried_again(client, book, ready, fake_ai, monkeypatch):
    pid = book["priya"]["id"]
    def broken(prompt, system=None, choice="auto", purpose=None):
        raise ai.AIError("Ollama isn't reachable")
    monkeypatch.setattr(ai, "complete", broken)
    q = client.post(f"/api/crm/people/{pid}/questions", json={"question": "Who is she?"}).json()
    jobs.drain()
    failed = client.get(f"/api/crm/people/{pid}/questions").json()[0]
    assert failed["status"] == "error" and "reachable" in failed["error"]
    monkeypatch.setattr(ai, "complete", fake_ai)
    assert client.post(f"/api/crm/questions/{q['id']}/retry").json()["status"] == "queued"
    jobs.drain()
    assert client.get(f"/api/crm/people/{pid}/questions").json()[0]["status"] == "done"


def test_questions_need_words_a_person_and_someone_other_than_you(client, book, ready):
    pid = book["priya"]["id"]
    assert client.post(f"/api/crm/people/{pid}/questions", json={"question": "   "}).status_code == 422
    assert client.post(f"/api/crm/people/{pid}/questions", json={"question": "x" * 2001}).status_code == 422
    assert client.post(f"/api/crm/people/{book['me']['id']}/questions", json={"question": "Hi?"}).status_code == 422
    assert client.get("/api/crm/people/nobody/overview").status_code == 404
    helio = client.get("/api/crm/organizations").json()["items"][0]["org"]
    assert client.get(f"/api/crm/people/{helio['id']}/overview").status_code == 422


def test_deleting_a_person_takes_their_overview_and_questions(client, book, ready, fake_ai):
    pid = book["priya"]["id"]
    overview(client, book["priya"])
    client.post(f"/api/crm/people/{pid}/questions", json={"question": "Who is she?"})
    jobs.drain()
    client.delete(f"/api/crm/entities/{pid}")
    assert db.one("SELECT count(*) AS n FROM crm_overviews")["n"] == 0
    assert db.one("SELECT count(*) AS n FROM crm_questions")["n"] == 0


def test_the_research_brief_names_people_you_both_know(client, book):
    dana = make(client, "person", "Dana Okafor")
    link(client, book["me"], "knows", dana)
    link(client, dana, "knows", book["bare"])
    r = client.get(f"/api/crm/people/{book['bare']['id']}/research/brief")
    assert r.status_code == 200 and "People we both know: Dana Okafor." in r.json()["text"]


def test_the_home_finder_puts_names_that_match_first(client, book):
    make(client, "person", "Jon Sandoval", attributes={"title": "Engineering Lead"})
    make(client, "person", "Ana Erikson")
    erik = make(client, "person", "Erik Pruitt")
    client.put(f"/api/crm/people/{erik['id']}/connection", json={"strength": 5})
    found = client.get("/api/crm/people", params={"q": "eri", "sort": "match"}).json()["items"]
    # Erik's first name and Ana's surname start with it; Jon only has it in his title, so he comes last
    assert [r["person"]["name"] for r in found] == ["Erik Pruitt", "Ana Erikson", "Jon Sandoval"]
