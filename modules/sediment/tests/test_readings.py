"""Readings (readings.py), with People's records made through its API and a fake AI (conftest's fake_structured),
so these check what Sediment sends, keeps and checks, not what a model would say."""
import pytest

from core.server import ai, jobs
from modules.sediment.server import readings
from modules.sediment.server.readings import Evidence, Reading

READY = {"provider": "ollama", "label": "Ollama", "model": "qwen", "ready": True, "reason": "", "local": True}


def make(client, kind, name, **extra):
    r = client.post("/api/crm/entities", json={"kind": kind, "name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def link(client, source, kind, target):
    r = client.post("/api/crm/relationships", json={"source_id": source["id"], "target_id": target["id"], "kind": kind})
    assert r.status_code == 201, r.text


def note(client, entity, body, when=None):
    r = client.post(f"/api/crm/entities/{entity['id']}/notes", json={"body": body, **({"occurred_at": when} if when else {})})
    assert r.status_code in (200, 201), r.text


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(readings, "provider", lambda: dict(READY))


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    me = client.get("/api/crm/me").json()
    lumen = make(client, "organization", "Lumen Labs")
    link(client, me, "works_at", lumen)
    priya = make(client, "person", "Priya Nair", summary="Runs pilots at Helio.")
    note(client, priya, "Said Lumen Labs was the most responsive vendor she'd worked with.", "2026-09-01T10:00:00Z")
    note(client, priya, "Thinks Coldbox is overpriced for small fleets.", "2026-09-20T10:00:00Z")
    return {"me": me, "lumen": lumen, "priya": priya, "ref": f"crm:{priya['id']}"}


def warm(**extra) -> Reading:
    base = dict(stance="warm", confidence="high", summary="She seems to like working with you.",
                evidence=[Evidence(date="2026-09-01", source="Your notes on them", leans="warm", quoted=True,
                                   text="the most responsive vendor she'd worked with"),
                          Evidence(date="2031-01-01", source="Made up", leans="warm", quoted=True, text="I adore Lumen Labs forever"),
                          Evidence(date="", source="Your notes on them", leans="neutral", quoted=False, text="Runs pilots.")],
                drivers=["Fast answers"], change="", helps=["Ask about the next pilot"], unknowns=["Budget"])
    return Reading(**{**base, **extra})


def page(client, ref):
    r = client.get(f"/api/sediment/people/{ref}")
    assert r.status_code == 200, r.text
    return r.json()


def take(client, ref, subject, **extra):
    r = client.post(f"/api/sediment/people/{ref}/readings", json={"subject": subject, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_the_page_offers_you_your_company_and_saved_subjects(client, book, ready):
    p = page(client, book["ref"])
    assert p["person"]["name"] == "Priya Nair" and not p["missing"]
    assert [s["key"] for s in p["subjects"]] == ["me", "company"]
    assert p["subjects"][1]["name"] == "Lumen Labs"
    client.post("/api/sediment/subjects", json={"kind": "product", "name": "Coldbox", "description": "Our cold-chain sensor"})
    p = page(client, book["ref"])
    assert [s["name"] for s in p["subjects"]] == ["You", "Lumen Labs", "Coldbox"]
    assert p["subjects"][2]["key"].startswith("product:")


def test_a_reading_is_taken_checked_and_kept(client, book, ready, fake_structured):
    fake_structured.reply = warm()
    out = take(client, book["ref"], "company")
    assert out["unchanged"] is False and out["reading"]["status"] == "queued"
    jobs.drain()
    [r] = page(client, book["ref"])["readings"]
    assert r["status"] == "done" and r["stance"] == "warm" and r["subject_name"] == "Lumen Labs"
    assert r["written_by"] and r["person_name"] == "Priya Nair"
    real, invented, plain = r["body"]["evidence"]
    assert real["quoted"] is True and real["date"] == "2026-09-01"
    assert invented["quoted"] is False and invented["date"] == ""      # not in the records: a paraphrase, undated
    assert plain["quoted"] is False
    assert r["confidence"] == "high"
    call = fake_structured.calls[-1]
    assert call["schema"] is Reading and "most responsive vendor" in call["prompt"]
    assert "your company, Lumen Labs" in call["prompt"]
    assert call["choice"] == readings.choice()


def test_nothing_new_on_file_is_said_instead_of_spending(client, book, ready, fake_structured):
    fake_structured.reply = warm()
    take(client, book["ref"], "me")
    jobs.drain()
    again = take(client, book["ref"], "me")
    assert again["unchanged"] is True and again["since"]
    assert len(fake_structured.calls) == 1
    forced = take(client, book["ref"], "me", again=True)
    assert forced["unchanged"] is False
    jobs.drain()
    note(client, book["priya"], "Asked for a second pilot.")
    assert take(client, book["ref"], "me")["unchanged"] is False      # something new: read again
    jobs.drain()
    assert len(page(client, book["ref"])["readings"]) == 3


def test_a_product_reading_sends_the_passages_that_name_it(client, book, ready, fake_structured):
    pid = client.post("/api/sediment/subjects", json={"kind": "product", "name": "Coldbox", "terms": ["the box"]}).json()["id"]
    fake_structured.reply = warm(stance="cool", confidence="medium", evidence=[])
    take(client, book["ref"], f"product:{pid}")
    jobs.drain()
    prompt = fake_structured.calls[-1]["prompt"]
    assert "Passages from your records that mention Coldbox" in prompt and "overpriced for small fleets" in prompt
    [r] = page(client, book["ref"])["readings"]
    assert r["stance"] == "cool" and r["confidence"] == "low"         # no evidence left: confidence held down


def test_another_person_from_the_book_can_be_a_subject(client, book, ready, fake_structured):
    sam = make(client, "person", "Sam Ortiz")
    note(client, book["priya"], "Sam Ortiz and she clashed over the pilot budget.")
    s = client.post("/api/sediment/subjects", json={"kind": "person", "ref": f"crm:{sam['id']}"}).json()
    assert s["name"] == "Sam Ortiz" and s["key"] == f"crm:{sam['id']}"
    assert client.post("/api/sediment/subjects", json={"kind": "person", "ref": f"crm:{sam['id']}"}).json()["id"] == s["id"]
    fake_structured.reply = warm(stance="cool")
    take(client, book["ref"], s["key"])
    jobs.drain()
    assert "clashed over the pilot budget" in fake_structured.calls[-1]["prompt"]
    assert page(client, book["ref"])["readings"][0]["subject_name"] == "Sam Ortiz"


def test_an_ai_that_cannot_answer_for_now_parks_the_reading(client, book, ready, fake_structured):
    fake_structured.reply = ai.AIError("Ollama: Waiting for memory: 2.6 GB is free", provider_down=True)
    take(client, book["ref"], "me")
    jobs.drain()
    [r] = page(client, book["ref"])["readings"]
    assert r["status"] == "queued" and r["job"]["status"] == "waiting" and "memory" in r["job"]["wait_reason"]
    fake_structured.reply = warm()
    assert client.post(f"/api/jobs/{r['job']['id']}/go", json={"force": True}).status_code == 202
    jobs.drain()
    assert page(client, book["ref"])["readings"][0]["status"] == "done"


def test_a_failure_stays_on_the_reading_and_can_be_tried_again(client, book, ready, fake_structured):
    fake_structured.reply = ai.AIError("The answer didn't fit the shape asked for")
    rid = take(client, book["ref"], "me")["reading"]["id"]
    jobs.drain()
    [r] = page(client, book["ref"])["readings"]
    assert r["status"] == "error" and "shape" in r["error"]
    fake_structured.reply = warm()
    assert client.post(f"/api/sediment/readings/{rid}/retry").status_code == 200
    jobs.drain()
    assert page(client, book["ref"])["readings"][0]["status"] == "done"


def test_no_ai_set_up_says_so(client, book, monkeypatch, fake_structured):
    monkeypatch.setattr(readings, "provider", lambda: {**READY, "ready": False, "reason": "Add an API key for Claude in Settings"})
    take(client, book["ref"], "me")
    jobs.drain()
    assert page(client, book["ref"])["readings"][0]["error"] == "Add an API key for Claude in Settings"
    assert fake_structured.calls == []


def test_you_cannot_be_read_and_strangers_are_not_found(client, book, ready):
    assert client.get(f"/api/sediment/people/crm:{book['me']['id']}").status_code == 422
    assert client.get("/api/sediment/people/core:me").status_code == 422
    assert client.post("/api/sediment/people/core:me/readings", json={"subject": "me"}).status_code == 422
    assert client.post("/api/sediment/people/crm:nobody/readings", json={"subject": "me"}).status_code == 404


def test_no_company_in_the_book_says_where_to_add_it(client, ready):
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    jo = make(client, "person", "Jo Park")
    p = page(client, f"crm:{jo['id']}")
    assert [s["key"] for s in p["subjects"]] == ["me"]
    r = client.post(f"/api/sediment/people/crm:{jo['id']}/readings", json={"subject": "company"})
    assert r.status_code == 422 and "your own profile" in r.json()["detail"]


def test_a_deleted_person_keeps_their_readings_until_you_delete_them(client, book, ready, fake_structured):
    fake_structured.reply = warm()
    take(client, book["ref"], "me")
    jobs.drain()
    assert client.delete(f"/api/crm/entities/{book['priya']['id']}").status_code in (200, 204)
    p = page(client, book["ref"])
    assert p["missing"] is True and p["person"]["name"] == "Priya Nair" and len(p["readings"]) == 1
    assert client.delete(f"/api/sediment/people/{book['ref']}").status_code == 204
    assert page(client, book["ref"])["readings"] == []


def test_readings_follow_a_merge(client, book, ready, fake_structured):
    twin = make(client, "person", "P. Nair")
    fake_structured.reply = warm()
    take(client, f"crm:{twin['id']}", "me")
    jobs.drain()
    assert client.post(f"/api/crm/entities/{twin['id']}/merge", json={"into_id": book["priya"]["id"]}).status_code == 200
    p = page(client, f"crm:{twin['id']}")
    assert p["person"]["ref"] == book["ref"] and len(p["readings"]) == 1
    assert len(page(client, book["ref"])["readings"]) == 1


def test_products_can_be_edited_and_deleted_and_are_in_the_export(client, book):
    s = client.post("/api/sediment/subjects", json={"kind": "product", "name": "Coldbox"}).json()
    assert client.post("/api/sediment/subjects", json={"kind": "product", "name": "  "}).status_code == 422
    r = client.patch(f"/api/sediment/subjects/{s['id']}", json={"name": "Coldbox 2", "description": "v2", "terms": ["CB2", " "]})
    assert r.json()["name"] == "Coldbox 2" and r.json()["terms"] == ["CB2"]
    from modules.sediment.server import store
    assert [x["name"] for x in store.export()["subjects"]] == ["Coldbox 2"]
    assert client.delete(f"/api/sediment/subjects/{s['id']}").status_code == 204
    assert client.get("/api/sediment/subjects").json() == []


def test_a_cloud_reading_carries_an_estimate(client, book, monkeypatch, fake_structured):
    monkeypatch.setattr(readings, "provider", lambda: {**READY, "provider": "anthropic", "label": "Claude",
                                                       "model": "claude-opus-5-5", "local": False})
    fake_structured.reply = warm()
    take(client, book["ref"], "me")
    jobs.drain()
    body = page(client, book["ref"])["readings"][0]["body"]
    assert 0 < body["estimate"] < 1 and body["characters"] > 100
