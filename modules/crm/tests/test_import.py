"""Spreadsheets, LinkedIn's export, recorded meetings and the webhook: the other ways in."""
import io

import openpyxl
import pytest
from crm_helpers import link, make, upload

from core.server import ai, jobs, settings
from modules.crm.server import ingest, inbox
from modules.crm.server.documents import ParsedSheet
from modules.crm.server.spreadsheets import ColumnMap, SheetMapping, heuristic_mapping


@pytest.fixture
def rules():
    settings.update({"crm.extraction_provider": "rules", "crm.utility_provider": "rules"})


def xlsx(rows):
    wb = openpyxl.Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def team(client):
    me = client.put("/api/crm/me", json={"name": "Alex Rivera"}).json()
    cc = make(client, "organization", "Cinder Labs")
    mickey = make(client, "person", "Mickey Fairweather")
    link(client, me, "works_at", cc)
    link(client, mickey, "works_at", cc)
    return me, mickey


CONTACTS = [
    ["Name", "Organization", "Role", "Category", "Email", "LinkedIn", "Met With", "Notes",
     "Relationship Strength (1-5)", "Last Contact", "Next Action", "Done?"],
    ["Name", "Organization", "Role", "Category", "Email", "LinkedIn", "Met With", "Notes",
     "Relationship Strength (1-5)", "Last Contact", "Next Action", "Done?"],  # a repeated header
    ["Jay Lamont", "OLAMI", "Executive Director", "Investor, Mentor", "jay@OLAMI.example",
     "linkedin.com/in/jay", "Mickey", "Sat next to him at the opening", 4, "2026-09-10", "Send deck", True],
    ["Shula Marek", "OLAMI", "EIR", "Advisor", "", "", "", "Wants the pilot data", 3, "", "", False],
]


# ── Spreadsheets ──────────────────────────────────────────────────────

def test_headers_are_recognized_without_any_ai():
    m = heuristic_mapping(ParsedSheet("Contacts", [[str(c) for c in r] for r in CONTACTS]))
    targets = {c.column: c.target for c in m.columns}
    assert m.header_row == 1 and m.row_kind == "person"
    assert targets["Name"] == "name" and targets["Organization"] == "organization"
    assert targets["Role"] == "title" and targets["Category"] == "tags"
    assert targets["Met With"] == "met_with" and targets["Relationship Strength (1-5)"] == "relationship_strength"
    assert targets["Last Contact"] == "last_contact" and targets["Done?"] == "ignore"
    assert targets["Notes"] == "note" and targets["Next Action"] == "note"
    assert heuristic_mapping(ParsedSheet("X", [["a", "b"], ["1", "2"]])).row_kind == "skip"


def test_a_contact_sheet_becomes_people_organizations_lines_tags_and_notes(client, rules):
    team(client)
    job = upload(client, ("Contacts Tracker.xlsx", xlsx(CONTACTS)))["Contacts Tracker.xlsx"]
    assert job["status"] == "applied", job
    assert job["result"] == {"rows": 2, "people_created": 2, "people_updated": 0, "orgs_created": 1, "relationships": 5,
                             "notes": 2, "skipped_rows": 0}
    assert job["proposal"]["sheets"]["Sheet"]["mapped_by"] == "rules" and job["extractor"] == "rules"

    jay = client.get("/api/crm/entities", params={"q": "Jay Lamont"}).json()["items"][0]
    assert jay["attributes"]["email"] == "jay@OLAMI.example"
    assert jay["attributes"]["linkedin_url"] == "https://linkedin.com/in/jay"
    assert jay["attributes"]["last_contact"] == "2026-09-10" and set(jay["tags"]) == {"investor", "mentor"}
    rels = {(r["kind"], r["other"]["name"]): r for r in client.get(f"/api/crm/entities/{jay['id']}").json()["relationships"]}
    assert ("works_at", "OLAMI") in rels
    assert rels[("knows", "Mickey Fairweather")]["strength"] == 3        # a teammate met them
    assert rels[("knows", "Alex Rivera")]["strength"] == 4          # the owner's strength column
    notes = client.get(f"/api/crm/entities/{jay['id']}/notes").json()
    assert "Next Action: Send deck" in notes[0]["body"] and notes[0]["occurred_at"].startswith("2026-09-10")


def test_the_same_spreadsheet_is_not_imported_twice_even_renamed(client, rules):
    team(client)
    upload(client, ("a.xlsx", xlsx(CONTACTS)))
    again = upload(client, ("copy of a.xlsx", xlsx(CONTACTS)))["copy of a.xlsx"]
    assert again["status"] == "skipped" and "Already imported" in again["error"]
    assert client.get("/api/crm/entities", params={"q": "Jay Lamont"}).json()["total"] == 1


QUIRKS = [
    ["Name", "Organization", "Role", "Category", "Email", "Notes"],
    ["Heather Quinn", "ORTADA / OBX", "Executive Director", "Mentor", "hquinn@ortada.example", "Showcase host"],
    ["Heather", "ORTADA / OBX Inc", "?", "", "", "Met at BVC"],
    ["Pat", "Acme", "", "", "", "first name only, first sighting"],
    ["Pat Lee", "Acme", "Engineer", "", "", "full name arrives later"],
    ["The Ford Family Foundation", "The Ford Family Foundation", "Sponsor", "Organization", "info@tfff.example", "Funds rural Oregon"],
    ["Launch Program", "Big University", "", "Program", "", "Accelerator track"],
    ["–", "Lab Corp", "–", "", "", "Oregon vaccine transport"],
    ["555-010-0198", "", "", "", "", ""],
    ["Sam Stone", "na", "", "", "", ""],
]


def test_the_odd_rows_in_a_real_sheet_are_handled(client, rules):
    team(client)
    job = upload(client, ("Quirks.xlsx", xlsx(QUIRKS)))["Quirks.xlsx"]
    assert job["status"] == "applied", job
    people = {e["name"]: e for e in client.get("/api/crm/entities", params={"kind": "person", "limit": 100}).json()["items"]}
    orgs = {e["name"]: e for e in client.get("/api/crm/entities", params={"kind": "organization", "limit": 100}).json()["items"]}

    # "Heather" at ORTADA is Heather Quinn, the organization's spelling difference doesn't split them, and "?" is no title.
    assert "Heather" not in people and people["Heather Quinn"]["attributes"]["title"] == "Executive Director"
    assert [n for n in orgs if n.startswith("ORTADA")] == ["ORTADA / OBX"]
    # A first-name-only record is upgraded when the full name turns up at the same organization.
    assert "Pat" not in people and people["Pat Lee"]["attributes"]["aliases"] == ["Pat"]
    # An organization's own row is an organization, not a person who works at themselves.
    assert "The Ford Family Foundation" not in people
    ford = orgs["The Ford Family Foundation"]
    assert ford["attributes"]["email"] == "info@tfff.example" and "sponsor" in ford["tags"] and "organization" not in ford["tags"]
    program = client.get(f"/api/crm/entities/{orgs['Launch Program']['id']}").json()
    assert [(r["kind"], r["other"]["name"]) for r in program["relationships"]] == [("part_of", "Big University")]
    # Placeholders and stray phone numbers make no records; the note lands on the organization.
    assert "–" not in people and "555-010-0198" not in people and "na" not in orgs
    assert "Oregon vaccine transport" in client.get(f"/api/crm/entities/{orgs['Lab Corp']['id']}/notes").json()[0]["body"]
    assert people["Sam Stone"]["subtitle"] is None
    assert job["result"]["skipped_rows"] == 1


def test_an_event_sheet_makes_the_event_and_who_was_there(client, rules):
    team(client)
    mapping = SheetMapping(header_row=1, row_kind="person", event_name="Innovation Showcase", event_date="2026-04-02",
                           sheet_tags=["Showcase"], columns=[ColumnMap(column="Name", target="name"), ColumnMap(column="Met", target="met_with")])
    sheet = ParsedSheet("Sheet1", [["Name", "Met"], ["Zed Zulu", "Mickey"]])
    row = inbox.create("spreadsheet", title="Showcase", payload={"filename": "Showcase.xlsx",
                       "sheets": [{"name": sheet.name, "rows": sheet.rows}], "mappings": {"Sheet1": mapping.model_dump()}})
    ingest.process_spreadsheet(row)    # a recorded mapping is replayed, not asked for again
    meeting = client.get("/api/crm/entities", params={"kind": "meeting"}).json()["items"][0]
    assert meeting["name"] == "Innovation Showcase" and meeting["occurred_at"].startswith("2026-04-02") and "showcase" in meeting["tags"]
    ctx = client.get(f"/api/crm/entities/{meeting['id']}/context").json()
    assert {p["person"]["name"] for p in ctx["people"]} == {"Alex Rivera", "Mickey Fairweather", "Zed Zulu"}
    assert inbox.require(row["id"])["status"] == "applied"


def test_the_ai_maps_the_columns_and_the_synonym_fallback_covers_a_bad_answer(client, fake_structured):
    team(client)
    sheet = [["Who", "Where they work", "Tell me more"], ["Zed Zulu", "Acme", "Great chat"]]
    fake_structured.reply = SheetMapping(header_row=1, row_kind="person", columns=[
        ColumnMap(column="Who", target="name"), ColumnMap(column="Where they work", target="organization"),
        ColumnMap(column="Tell me more", target="note")])
    job = upload(client, ("odd.xlsx", xlsx(sheet)))["odd.xlsx"]
    assert job["status"] == "applied" and job["proposal"]["sheets"]["Sheet"]["mapped_by"].startswith("anthropic:")
    assert job["result"]["people_created"] == 1 and fake_structured.calls[0]["choice"] == "gemini"   # the quick model reads columns
    assert "Where they work" in fake_structured.calls[0]["prompt"]

    # An answer that names headers that aren't in the sheet is not trusted.
    fake_structured.reply = SheetMapping(header_row=1, row_kind="person", columns=[ColumnMap(column="Nonsense", target="name")])
    other = upload(client, ("normal.xlsx", xlsx([["Name", "Organization"], ["Amy Pond", "Pond Labs"]])))["normal.xlsx"]
    assert other["proposal"]["sheets"]["Sheet"]["mapped_by"] == "rules" and other["result"]["people_created"] == 1


def test_when_the_provider_is_down_a_spreadsheet_waits_instead_of_being_mapped_by_guesswork(client, fake_structured):
    team(client)
    fake_structured.reply = ai.AIError("Gemini rejected the API key", provider_down=True)
    job = upload(client, ("p.xlsx", xlsx([["Name", "Organization"], ["Amy Pond", "Pond Labs"]])))["p.xlsx"]
    assert job["status"] == "pending" and job["work"]["status"] == "waiting"
    assert client.get("/api/crm/entities", params={"q": "Amy Pond"}).json()["total"] == 0
    fake_structured.reply = SheetMapping(header_row=1, row_kind="person", columns=[ColumnMap(column="Name", target="name")])
    assert client.post("/api/crm/ingest/resume").json()["resumed"] == 1
    jobs.drain()
    assert inbox.require(job["id"])["status"] == "applied"
    assert client.get("/api/crm/entities", params={"q": "Amy Pond"}).json()["total"] == 1


def test_a_spreadsheet_import_is_all_or_nothing(client, rules, monkeypatch):
    team(client)
    monkeypatch.setattr("modules.crm.server.store.add_note", lambda *a, **k: 1 / 0)
    job = upload(client, ("a.xlsx", xlsx(CONTACTS)))["a.xlsx"]
    assert job["status"] == "failed" and job["error"] == "division by zero"
    assert client.get("/api/crm/entities", params={"q": "Jay Lamont"}).json()["total"] == 0
    assert client.get("/api/crm/entities", params={"q": "OLAMI"}).json()["total"] == 0


# ── LinkedIn ──────────────────────────────────────────────────────────

LINKEDIN = """Notes:
"When exporting your connection data, you may notice that some of the email addresses are missing."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Priya,Nair,https://www.linkedin.com/in/priya-nair,,Helio Cold Chain,CEO,12 Mar 2024
Tom,Albright,https://www.linkedin.com/in/tomalbright/,tom@frostline.example,Frostline Logistics,VP Partnerships,01 Feb 2023
Lee,Kim,https://www.linkedin.com/in/leekim,,,,05 Jan 2022
"""


def test_a_linkedin_export_is_imported_once(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    existing = make(client, "person", "Priya Nair")
    files = {"file": ("Connections.csv", LINKEDIN.encode(), "text/csv")}
    r = client.post("/api/crm/ingest/linkedin", files=files)
    assert r.status_code == 201, r.text
    assert r.json()["result"] == {"rows": 3, "people_created": 2, "people_updated": 1, "orgs_created": 2, "relationships": 5}
    assert r.json()["status"] == "applied" and r.json()["source"] == "linkedin_csv"
    priya = client.get(f"/api/crm/entities/{existing['id']}").json()
    assert priya["entity"]["attributes"]["linkedin_url"] == "https://www.linkedin.com/in/priya-nair"
    knows = next(x for x in priya["relationships"] if x["kind"] == "knows")
    assert knows["other"]["id"] == me["id"] and knows["started_at"] == "2024-03-12"
    again = client.post("/api/crm/ingest/linkedin", files=files)
    assert again.json()["result"] == {"rows": 3, "people_created": 0, "people_updated": 0, "orgs_created": 0, "relationships": 0}


def test_something_that_isnt_a_linkedin_export_is_refused(client):
    assert client.post("/api/crm/ingest/linkedin", files={"file": ("x.csv", b"name,email\na,b\n", "text/csv")}).status_code == 422
    assert client.post("/api/crm/ingest/linkedin", files={"file": ("x.csv", b"First Name,Last Name,URL\n", "text/csv")}).status_code == 422


# ── Recorded meetings ─────────────────────────────────────────────────

GRANOLA = {
    "origin": "granola", "external_id": "gr-123", "title": "Pilot planning with Ana", "started_at": "2026-09-20T17:00:00Z",
    "attendees": [{"name": "Me", "email": "me@example.com", "is_self": True}, {"name": "Ana Ruiz", "email": "ana@helio.example"},
                  {"email": "raj.patel@helio.example"}],
    "transcript": "Ana: thanks for making time. Raj: the pilot needs 40 fridges by March.\nMe: we can do that.",
}


def test_a_replayed_recorded_meeting_does_not_duplicate(client, rules):
    client.put("/api/crm/me", json={"name": "Me"})
    make(client, "person", "Ana R.", attributes={"email": "ana@helio.example"})
    r = client.post("/api/crm/ingest/meeting", json=GRANOLA)
    assert r.status_code == 202, r.text
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    assert row["status"] == "applied", row
    ctx = client.get(f"/api/crm/entities/{row['result']['record_id']}/context").json()
    # Ana matched by email despite the different spelling; Raj was made from his email.
    assert {(p["person"]["name"], p["relation"]) for p in ctx["people"]} == {("Me", "attended"), ("Ana R.", "attended"), ("Raj Patel", "attended")}
    for body in (GRANOLA, {**GRANOLA, "external_id": "gr-999"}):   # the same id again, and the same text under a new id
        again = client.post("/api/crm/ingest/meeting", json=body)
        assert again.status_code == 200 and again.json()["id"] == row["id"]
    assert client.get("/api/crm/entities", params={"kind": "meeting"}).json()["total"] == 1


def test_a_recorded_meeting_adds_to_the_meeting_you_already_noted(client, rules):
    client.put("/api/crm/me", json={"name": "Me"})
    ana = make(client, "person", "Ana Ruiz")
    earlier = make(client, "meeting", "Pilot planning", occurred_at="2026-09-20T16:00:00Z", summary="From my notes.")
    link(client, ana, "attended", earlier)
    r = client.post("/api/crm/ingest/meeting", json={**GRANOLA, "external_id": "gr-456"})
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    assert row["status"] == "applied" and row["result"]["record_id"] == earlier["id"]
    assert client.get("/api/crm/entities", params={"kind": "meeting"}).json()["total"] == 1
    kept = client.get(f"/api/crm/entities/{earlier['id']}").json()["entity"]
    assert kept["summary"] == "From my notes." and kept["attributes"]["external_ids"] == {"granola": "gr-456"}


def test_a_recorded_meeting_needs_something_to_read_and_a_sane_origin(client):
    assert client.post("/api/crm/ingest/meeting", json={"title": "Empty"}).status_code == 422
    assert client.post("/api/crm/ingest/meeting", json={**GRANOLA, "origin": 'a"b'}).status_code == 422


# ── The webhook ───────────────────────────────────────────────────────

def test_the_webhook_takes_the_shapes_note_takers_send(client, rules):
    payload = {"data": {"title": "Weekly sync", "date": "2026-06-01", "transcript": "We reviewed the roadmap and the budget for the next quarter.",
                        "participants": [{"name": "Lee Kim", "email": "lee@k.example"}, "Pat Ray"]}}
    r = client.post("/api/crm/ingest/webhook", json=payload)
    assert r.status_code == 202, r.text
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    assert row["source"] == "webhook" and row["title"] == "Weekly sync" and row["occurred_at"].startswith("2026-06-01")
    assert row["status"] == "review"      # a webhook waits for you unless you've said otherwise
    assert {e["name"] for e in row["proposal"]["entities"]} == {"Lee Kim", "Pat Ray"}
    assert client.post("/api/crm/ingest/webhook", json={"title": "x"}).status_code == 422


def test_a_webhook_is_added_automatically_only_when_you_turn_that_on(client, rules):
    settings.update({"crm.webhook_auto_apply": True})
    r = client.post("/api/crm/ingest/webhook", json={"text": "Attendees: Zed Zulu\nA note about the depot pilot with enough words in it."})
    jobs.drain()
    assert client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()["status"] == "applied"
