"""Roundups: packets about a set of people, for someone to take to an event (roundups.py, roundup_files.py).

The AI is a fake (conftest's fake_ai), so these check what goes into the packet and its files, not what a model would say."""
import io
import zipfile

import pytest
from crm_helpers import link, make
from PIL import Image

from core.server import config, db, jobs
from modules.crm.server import profiles, roundup_files

READY = {"provider": "ollama", "label": "Ollama", "model": "qwen", "ready": True, "reason": "", "local": True}


def _jpeg() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (64, 64), (40, 90, 70)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(profiles, "provider", lambda: dict(READY))


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera", "title": "Founder"})
    northwind = make(client, "organization", "Northwind")
    kestrel = make(client, "organization", "Kestrel")
    ana = make(client, "person", "Ana Ruiz", attributes={"title": "Director", "email": "ana@northwind.example",
                                                         "linkedin_url": "https://www.linkedin.com/in/anaruiz"})
    ben = make(client, "person", "Ben Okafor", summary="Runs the lab programme at Northwind. " * 80)
    cy = make(client, "person", "Cy Tran", attributes={"title": "Program Manager"})
    link(client, ana, "works_at", northwind, properties={"title": "Director"})
    link(client, ben, "works_at", northwind)
    link(client, cy, "works_at", kestrel)
    link(client, ana, "knows", cy)
    db.execute("INSERT INTO crm_overviews (id, entity_id, body, fingerprint, written_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
               (db.new_id(), ana["id"], "Ana runs Northwind's incubator.\n\n**Worth knowing**\n- Back from **Berlin**\n- See [her talk](https://example.com/talk)",
                "x", "fake", "2026-11-01T00:00:00Z"))
    client.put(f"/api/crm/pictures/{ana['id']}", content=_jpeg(), headers={"Content-Type": "image/jpeg"})
    return {"northwind": northwind, "kestrel": kestrel, "ana": ana, "ben": ben, "cy": cy}


def prepared(client, rid):
    r = client.post(f"/api/crm/roundups/{rid}/prepare")
    assert r.status_code == 200, r.text
    jobs.drain()
    return client.get(f"/api/crm/roundups/{rid}").json()


def test_a_group_starts_a_roundup_and_people_can_be_added_one_by_one(client, book):
    groups = client.get("/api/crm/roundups/groups").json()
    northwind = next(g for g in groups if g["name"] == "Northwind")
    assert northwind["kind"] == "organization" and northwind["size"] == 2
    r = client.post("/api/crm/roundups", json={"group": northwind["id"], "event": "Cold Chain Summit"})
    assert r.status_code == 201, r.text
    rup = r.json()
    assert rup["title"] == "Northwind roundup" and rup["origin_name"] == "Northwind"
    assert {p["name"] for p in rup["people"]} == {"Ana Ruiz", "Ben Okafor"}
    rup = client.post(f"/api/crm/roundups/{rup['id']}/people", json={"people": [book["cy"]["id"], book["ana"]["id"]]}).json()
    assert [p["name"] for p in rup["people"]][-1] == "Cy Tran" and len(rup["people"]) == 3     # no one twice
    me = client.get("/api/crm/me").json()
    assert client.post(f"/api/crm/roundups/{rup['id']}/people", json={"people": [me["id"]]}).status_code == 422
    listed = client.get("/api/crm/roundups").json()
    assert [(x["title"], x["people"], x["prepared_at"]) for x in listed] == [("Northwind roundup", 3, None)]


def test_preparing_writes_a_line_on_each_person_then_the_opening(client, book, ready, fake_ai):
    rup = client.post("/api/crm/roundups", json={"title": "Mixer", "event": "Cold Chain Summit: ask about lab space",
                                                 "audience": "Sam", "people": [book["ana"]["id"], book["cy"]["id"]]}).json()
    fake_ai.reply = "A short line."
    done = prepared(client, rup["id"])
    packet = done["packet"]
    assert len(fake_ai.prompts) == 3 and not done["stale"]
    ana_prompt, cy_prompt, opening = fake_ai.prompts
    for fact in ("Ana Ruiz", "Director at Northwind", "Ana runs Northwind's incubator.", "Cold Chain Summit: ask about lab space",
                 "The packet is for Sam", "call the owner Alex", "Cy Tran (knows, also in this packet)"):
        assert fact in ana_prompt, fact
    assert "ana@northwind.example" not in ana_prompt                       # addresses stay out of what the model sees
    assert "Nothing else is on file" in cy_prompt
    assert "- Ana Ruiz, Director at Northwind: A short line. (connected to Cy Tran)" in opening
    ana = packet["people"][0]
    assert ana["blurb"] == "A short line." and ana["linkedin"].endswith("/anaruiz") and ana["summary_from"] == "overview"
    assert ana["organizations"] == [{"name": "Northwind", "role": "Director", "current": True}]
    assert ana["connections"][0]["name"] == "Cy Tran" and ana["connections"][0]["in_packet"]
    assert "picture" not in ana                                       # the page shows the live one
    assert packet["intro"] == "A short line." and packet["owner"] == "Alex Rivera"


def test_a_long_profile_summary_stands_in_for_a_missing_overview_cut_short(client, book, ready, fake_ai):
    rup = client.post("/api/crm/roundups", json={"people": [book["ben"]["id"]]}).json()
    ben = prepared(client, rup["id"])["packet"]["people"][0]
    assert ben["summary_from"] == "profile" and len(ben["summary"]) <= 1_200 and ben["summary"].endswith(".")


def test_a_change_after_preparing_marks_it_out_of_date(client, book, ready, fake_ai):
    rup = client.post("/api/crm/roundups", json={"people": [book["ana"]["id"], book["cy"]["id"]]}).json()
    prepared(client, rup["id"])
    changed = client.patch(f"/api/crm/roundups/{rup['id']}", json={"people": [book["ana"]["id"]], "event": "Gala"}).json()
    assert changed["stale"] and changed["packet"]["people"][1]["name"] == "Cy Tran"   # the old packet stays until it's redone
    again = prepared(client, rup["id"])
    assert not again["stale"] and [p["name"] for p in again["packet"]["people"]] == ["Ana Ruiz"]


def test_a_job_that_stops_part_way_keeps_the_lines_it_wrote(client, book, ready, monkeypatch):
    from core.server import ai
    rup = client.post("/api/crm/roundups", json={"people": [book["ana"]["id"], book["cy"]["id"]]}).json()
    calls = []

    def flaky(prompt, system=None, choice="auto", purpose=None, models=None):
        calls.append(prompt)
        if len(calls) == 2:
            raise ai.AIError("The model stopped")
        return "Line.", "fake"

    monkeypatch.setattr(ai, "complete", flaky)
    after = prepared(client, rup["id"])
    assert after["job"]["status"] == "error" and after["packet"] is None
    prepared(client, rup["id"])
    assert len(calls) == 4 and "Cy Tran" in calls[2] and "The people in it" in calls[3]   # Ana's line wasn't written again


def test_preparing_needs_people_and_an_ai(client, book, monkeypatch):
    empty = client.post("/api/crm/roundups", json={"title": "Empty"}).json()
    assert client.post(f"/api/crm/roundups/{empty['id']}/prepare").status_code == 422
    monkeypatch.setattr(profiles, "provider", lambda: {**READY, "ready": False, "reason": "Add an API key"})
    rup = client.post("/api/crm/roundups", json={"people": [book["ana"]["id"]]}).json()
    r = client.post(f"/api/crm/roundups/{rup['id']}/prepare")
    assert r.status_code == 422 and r.json()["detail"] == "Add an API key"


def test_exports_are_saved_in_the_roundups_folder_in_each_format(client, book, ready, fake_ai):
    fake_ai.reply = "Opening paragraph with **bold** and a [link](https://example.com)."
    rup = client.post("/api/crm/roundups", json={"title": "Northwind / Kestrel: night", "audience": "Sam",
                                                 "people": [book["ana"]["id"], book["cy"]["id"]]}).json()
    assert client.post(f"/api/crm/roundups/{rup['id']}/export", json={"format": "pdf"}).status_code == 422   # not prepared
    prepared(client, rup["id"])
    saved = {}
    for fmt in ("docx", "pdf", "md"):
        r = client.post(f"/api/crm/roundups/{rup['id']}/export", json={"format": fmt})
        assert r.status_code == 200, r.text
        saved[fmt] = r.json()
        assert saved[fmt]["folder"] == str(config.DATA_DIR / "crm" / "roundups" / rup["id"])
        assert saved[fmt]["name"].startswith("Northwind Kestrel night ") and saved[fmt]["name"].endswith(f".{fmt}")
    files = client.get(f"/api/crm/roundups/{rup['id']}").json()["files"]
    assert sorted(f["format"] for f in files) == ["docx", "md", "pdf"]

    md = client.get(f"/api/crm/roundups/{rup['id']}/files/{saved['md']['name']}")
    assert md.status_code == 200 and "attachment" in md.headers["content-disposition"]
    text = md.text
    for piece in ("# Northwind / Kestrel: night", "Prepared for Sam by Alex Rivera", "## At a glance", "## Ana Ruiz",
                  "[LinkedIn](https://www.linkedin.com/in/anaruiz)", "**For this event:**", "### Closest connections",
                  "- Northwind, Director", "where they say “you”, that's Alex"):
        assert piece in text, piece

    docx = client.get(f"/api/crm/roundups/{rup['id']}/files/{saved['docx']['name']}").content
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        xml = z.read("word/document.xml").decode()
        assert any(n.startswith("word/media/") for n in z.namelist())          # Ana's picture
    assert "Ana Ruiz" in xml and "Berlin" in xml and "Closest connections" in xml

    pdf = client.get(f"/api/crm/roundups/{rup['id']}/files/{saved['pdf']['name']}")
    assert pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert client.get(f"/api/crm/roundups/{rup['id']}/files/..%2Flodge.db").status_code == 404


def test_deleting_a_roundup_forgets_it(client, book):
    rup = client.post("/api/crm/roundups", json={"people": [book["ana"]["id"]]}).json()
    assert client.delete(f"/api/crm/roundups/{rup['id']}").status_code == 204
    assert client.get(f"/api/crm/roundups/{rup['id']}").status_code == 404
    assert client.get("/api/crm/roundups").json() == []


def test_markdown_is_read_into_blocks_and_runs():
    md = "Intro line\ncontinues.\n\n**Worth knowing**\n- one *two*\n- [three](https://x.example)\n\n## Head"
    assert roundup_files.blocks(md) == [("p", "Intro line continues."), ("p", "**Worth knowing**"),
                                        ("li", "one *two*"), ("li", "[three](https://x.example)"), ("h", "Head")]
    assert roundup_files.runs("a **b** *c* [d](u) snake_case") == [
        ("a ", False, False, None), ("b", True, False, None), (" ", False, False, None), ("c", False, True, None),
        (" ", False, False, None), ("d", False, False, "u"), (" snake_case", False, False, None)]
