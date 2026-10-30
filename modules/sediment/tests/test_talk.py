"""Portraits and rehearsals (talk.py), with People's records made through its API and fake AIs (conftest's fake_ai and
fake_structured), so these check what's sent, kept and checked, not what a model would say."""
import pytest

from core.server import ai, db, jobs
from modules.sediment.server import store, talk
from modules.sediment.server.talk import Ground, Reply

READY = {"provider": "ollama", "label": "Ollama", "model": "qwen", "ready": True, "reason": "", "local": True}
TRANSCRIPT = """Meeting: Pilot review

## Transcript
Me: How did the pilot go?
Them: Honestly, the trucks worked well but Frostline was slow to answer.
Me: Would you do another?
Them: Only if the pricing comes down for small fleets."""


def make(client, kind, name, **extra):
    r = client.post("/api/crm/entities", json={"kind": kind, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def link(client, source, kind, target):
    assert client.post("/api/crm/relationships", json={"source_id": source["id"], "target_id": target["id"], "kind": kind}).status_code == 201


def note(client, entity, body, when=None):
    r = client.post(f"/api/crm/entities/{entity['id']}/notes", json={"body": body, **({"occurred_at": when} if when else {})})
    assert r.status_code in (200, 201), r.text


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(talk, "provider", lambda: dict(READY))


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    me = client.get("/api/crm/me").json()
    priya = make(client, "person", "Priya Nair", summary="Runs pilots at Helio.")
    review = make(client, "meeting", "Pilot review", occurred_at="2026-09-14T15:00:00Z")
    link(client, priya, "attended", review)
    link(client, me, "attended", review)
    note(client, review, TRANSCRIPT, "2026-09-14T15:00:00Z")
    note(client, priya, "Wants a second pilot if the numbers work.")
    return {"me": me, "priya": priya, "ref": f"crm:{priya['id']}"}


def portrait(client, ref):
    r = client.get(f"/api/sediment/people/{ref}/portrait")
    assert r.status_code == 200, r.text
    return r.json()


def start(client, ref, scenario=""):
    r = client.post(f"/api/sediment/people/{ref}/conversations", json={"scenario": scenario})
    assert r.status_code == 201, r.text
    return r.json()


def say(client, cid, text):
    return client.post(f"/api/sediment/conversations/{cid}/lines", json={"text": text})


def thread(client, cid):
    return client.get(f"/api/sediment/conversations/{cid}").json()["messages"]


def test_a_portrait_is_written_from_the_records_and_their_own_lines(client, book, ready, fake_ai):
    fake_ai.reply = "**How they talk**\nDirect.\n\n**What they care about**\n- Pricing"
    first = portrait(client, book["ref"])
    assert first["portrait"] is None and first["job"]["kind"] == "portrait" and first["voice"] == 2
    jobs.drain()
    after = portrait(client, book["ref"])
    assert after["portrait"]["body"].startswith("**How they talk**") and after["portrait"]["current"]
    prompt = fake_ai.prompts[-1]
    assert "Lines Priya said in meetings" in prompt and "Only if the pricing comes down for small fleets." in prompt
    assert "Would you do another?" not in prompt          # your own lines aren't theirs
    assert "Runs pilots at Helio." in prompt and "**Not on file**" in prompt


def test_a_portrait_is_written_again_only_when_the_records_change(client, book, ready, fake_ai):
    portrait(client, book["ref"])
    jobs.drain()
    portrait(client, book["ref"])
    jobs.drain()
    assert len(fake_ai.prompts) == 1
    note(client, book["priya"], "Moved to Lisbon.")
    assert portrait(client, book["ref"])["portrait"]["current"] is False
    jobs.drain()
    assert len(fake_ai.prompts) == 2
    assert client.post(f"/api/sediment/people/{book['ref']}/portrait").status_code == 200   # Redo, with nothing new
    jobs.drain()
    assert len(fake_ai.prompts) == 3


def test_a_rehearsal_reply_is_grounded_and_its_guesses_marked(client, book, ready, fake_ai, fake_structured):
    fake_ai.reply = "**How they talk**\nDirect and brief."
    portrait(client, book["ref"])
    jobs.drain()
    c = start(client, book["ref"], "I'm asking for a second pilot")
    assert c["scenario"] == "I'm asking for a second pilot" and c["messages"] == []
    fake_structured.reply = Reply(
        reply="Maybe, if the pricing comes down. I'd want my CFO in the room next time.",
        guesses=["I'd want my CFO in the room", "something I never said"],
        grounds=[Ground(phrase="if the pricing comes down", source="Pilot review, 2026-09-14"),
                 Ground(phrase="not in the reply", source="Nowhere")])
    r = say(client, c["id"], "Would you run a second pilot with us?")
    assert r.status_code == 201, r.text
    mine, theirs = r.json()["messages"]
    assert mine["role"] == "you" and mine["status"] == "done" and theirs["role"] == "them" and theirs["status"] == "queued"
    jobs.drain()
    _, theirs = thread(client, c["id"])
    assert theirs["status"] == "done" and theirs["body"].startswith("Maybe, if the pricing")
    assert theirs["guesses"] == ["I'd want my CFO in the room"]                   # made-up phrases not in the reply are dropped
    assert theirs["grounds"] == [{"phrase": "if the pricing comes down", "source": "Pilot review, 2026-09-14"}]
    call = fake_structured.calls[-1]
    assert call["schema"] is Reply and call["choice"] == talk.choice()
    assert "simulation" in call["system"] and "health, family" in call["system"] and "Priya" in call["system"]
    for part in ("I'm asking for a second pilot", "Portrait of Priya:\n**How they talk**\nDirect and brief.",
                 "You: Would you run a second pilot with us?", "Only if the pricing comes down for small fleets."):
        assert part in call["prompt"], part


def test_one_line_at_a_time(client, book, ready, fake_structured):
    fake_structured.reply = ai.AIError("Ollama: Waiting for memory", provider_down=True)    # the reply stays on its way
    c = start(client, book["ref"])
    assert say(client, c["id"], "Hi Priya").status_code == 201
    jobs.drain()
    r = say(client, c["id"], "Are you there?")
    assert r.status_code == 422 and r.json()["detail"] == "A reply is still on its way"
    assert say(client, c["id"], "  ").status_code == 422


def test_long_conversations_send_only_the_latest_lines(client, book, ready, fake_structured):
    c = start(client, book["ref"])
    for i in range(12):
        store.add_message(c["id"], "you", f"Line number {i} from you")
        store.add_message(c["id"], "them", f"Line number {i} from her")
    fake_structured.reply = Reply(reply="Fine.", guesses=[], grounds=[])
    say(client, c["id"], "And the last one?")
    jobs.drain()
    prompt = fake_structured.calls[-1]["prompt"]
    assert "the earliest 9 lines left out" in prompt
    assert "Line number 0 from you" not in prompt and "Line number 11 from her" in prompt and "You: And the last one?" in prompt


def test_an_ai_that_cannot_answer_for_now_waits_and_a_failure_can_be_tried_again(client, book, ready, fake_structured):
    c = start(client, book["ref"])
    fake_structured.reply = ai.AIError("Ollama: Waiting for memory", provider_down=True)
    say(client, c["id"], "Hi")
    jobs.drain()
    _, theirs = thread(client, c["id"])
    assert theirs["status"] == "queued" and theirs["job"]["status"] == "waiting"
    fake_structured.reply = ai.AIError("The answer didn't fit the shape asked for")
    client.post(f"/api/jobs/{theirs['job']['id']}/go", json={"force": True})
    jobs.drain()
    _, theirs = thread(client, c["id"])
    assert theirs["status"] == "error" and "shape" in theirs["error"]
    fake_structured.reply = Reply(reply="Sorry, go on.", guesses=[], grounds=[])
    assert client.post(f"/api/sediment/lines/{theirs['id']}/retry").status_code == 200
    jobs.drain()
    assert thread(client, c["id"])[1]["body"] == "Sorry, go on."


def test_you_cannot_rehearse_with_yourself(client, book, ready):
    assert client.post("/api/sediment/people/core:me/conversations", json={}).status_code == 422
    assert client.post(f"/api/sediment/people/crm:{book['me']['id']}/conversations", json={}).status_code == 422
    assert client.get(f"/api/sediment/people/crm:{book['me']['id']}/portrait").status_code == 422


def test_nothing_goes_back_into_people(client, book, ready, fake_ai, fake_structured):
    before = db.one("SELECT COUNT(*) AS n FROM crm_notes")["n"], db.one("SELECT COUNT(*) AS n FROM crm_entities")["n"]
    portrait(client, book["ref"])
    c = start(client, book["ref"])
    fake_structured.reply = Reply(reply="Sure.", guesses=["Sure."], grounds=[])
    say(client, c["id"], "Lunch next week?")
    jobs.drain()
    after = db.one("SELECT COUNT(*) AS n FROM crm_notes")["n"], db.one("SELECT COUNT(*) AS n FROM crm_entities")["n"]
    assert after == before


def test_conversations_are_listed_deleted_and_exported_as_simulated(client, book, ready, fake_structured):
    fake_structured.reply = Reply(reply="Hi.", guesses=[], grounds=[])
    c = start(client, book["ref"], "Catching up")
    say(client, c["id"], "Hello")
    jobs.drain()
    [listed] = client.get(f"/api/sediment/people/{book['ref']}/conversations").json()
    assert listed["id"] == c["id"] and listed["messages"] == 2
    [exported] = store.export()["conversations"]
    assert exported["simulated"] is True and [m["body"] for m in exported["messages"]] == ["Hello", "Hi."]
    assert client.delete(f"/api/sediment/conversations/{c['id']}").status_code == 204
    assert client.get(f"/api/sediment/people/{book['ref']}/conversations").json() == []


def test_forgetting_someone_removes_their_portrait_and_rehearsals_too(client, book, ready, fake_ai, fake_structured):
    portrait(client, book["ref"])
    fake_structured.reply = Reply(reply="Hi.", guesses=[], grounds=[])
    c = start(client, book["ref"])
    say(client, c["id"], "Hello")
    jobs.drain()
    assert client.delete(f"/api/sediment/people/{book['ref']}").status_code == 204
    assert store.portrait(book["ref"]) is None and store.conversations_of(book["ref"]) == []
    assert db.one("SELECT COUNT(*) AS n FROM sediment_messages")["n"] == 0
