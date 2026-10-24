"""The shared Google Sheet: The Lodge fills it, takes in what people change and add there, and never lets a slip on
the sheet (a deleted row, a cleared column, a cell typed over mid-sync) cost anything in the records.

The sheet is the real Apps Script (sheet_script.SCRIPT) running under Node against a stand-in for Google Sheets
(sheet_harness.mjs), reached through Google's redirect the way the real web app answers."""
import json
import shutil
import subprocess
import uuid
from pathlib import Path

import httpx
import pytest

from core.server import jobs, settings
from modules.crm.server import capture, sheet_script, sheet_sync, store

HARNESS = Path(__file__).with_name("sheet_harness.mjs")
LINK = "https://script.google.com/macros/s/AKfycbTest123/exec"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs Node to run the sheet's script")


class FakeSheet:
    """A spreadsheet in a JSON file, and the people editing it: tests change cells the way someone in Sheets would."""

    def __init__(self, folder: Path):
        self.script = folder / "sheet-script.js"
        self.script.write_text(sheet_script.SCRIPT)
        self.path = folder / "spreadsheet.json"
        self.state = {"name": "Team contacts", "url": "https://docs.google.com/spreadsheets/d/abc123/edit", "sheets": [
            {"name": "Sheet1", "cells": [], "maxRows": 1000, "maxCols": 26, "frozen": 0, "textCols": [], "textCells": {},
             "notes": {}, "bold": {}, "protections": []}]}
        self.actions: list[str] = []
        self.between = None        # someone typing between The Lodge's read and its write: fn(sheet)
        self.answer: httpx.Response | None = None
        self._echo: dict[str, str] = {}

    # What Google does: the web app answers a POST with a redirect, and the answer is fetched from there.
    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.answer is not None:
            return self.answer
        if request.url.host == "script.googleusercontent.com":
            assert request.method == "GET"   # Google's echo address only answers a GET
            return httpx.Response(200, text=self._echo.pop(request.url.params["user_content_key"]),
                                  headers={"content-type": "application/json"})
        assert request.method == "POST" and str(request.url) == LINK
        action = json.loads(request.content)["action"]
        self.actions.append(action)
        if action == "write" and self.between:
            self.between(self)
            self.between = None
        self.path.write_text(json.dumps(self.state))
        done = subprocess.run(["node", str(HARNESS), str(self.script), str(self.path)], input=request.content,
                              capture_output=True, check=True, timeout=30)
        self.state = json.loads(self.path.read_text())
        key = uuid.uuid4().hex
        self._echo[key] = done.stdout.decode()
        return httpx.Response(302, headers={"location": f"https://script.googleusercontent.com/macros/echo?user_content_key={key}"})

    # Reading and editing it like a person would.
    def tab(self, name: str) -> dict:
        return next(s for s in self.state["sheets"] if s["name"] == name)

    def headers(self, name: str) -> list[str]:
        cells = self.tab(name)["cells"]
        return [h for h in (cells[0] if cells else []) if h]

    def rows(self, name: str) -> list[dict]:
        cells = self.tab(name)["cells"]
        heads = cells[0] if cells else []
        out = []
        for row in cells[1:]:
            if any(row):
                out.append({h: (row[i] if i < len(row) else "") for i, h in enumerate(heads) if h})
        return out

    def row(self, name: str, who: str) -> dict:
        hits = [r for r in self.rows(name) if r.get("Name") == who]
        assert len(hits) == 1, f"{len(hits)} rows for {who}"
        return hits[0]

    def number(self, name: str, who: str) -> int:
        cells = self.tab(name)["cells"]
        col = cells[0].index("Name")
        hits = [i + 1 for i, row in enumerate(cells) if i and col < len(row) and row[col] == who]
        assert len(hits) == 1, f"{len(hits)} rows for {who}"
        return hits[0]

    def set(self, name: str, who: str, header: str, value: str) -> None:
        self.put(name, self.number(name, who), header, value)

    def put(self, name: str, row: int, header: str, value: str) -> None:
        cells = self.tab(name)["cells"]
        col = cells[0].index(header)
        while len(cells) < row:
            cells.append([])
        while len(cells[row - 1]) <= col:
            cells[row - 1].append("")
        cells[row - 1][col] = value

    def add(self, name: str, values: dict) -> int:
        cells = self.tab(name)["cells"]
        last = max((i + 1 for i, row in enumerate(cells) if any(row)), default=1)
        for header, value in values.items():
            self.put(name, last + 1, header, value)
        return last + 1

    def delete(self, name: str, who: str) -> None:
        t = self.tab(name)
        t["cells"].pop(self.number(name, who) - 1)
        t["maxRows"] -= 1

    def copy_row(self, name: str, who: str) -> int:
        cells = self.tab(name)["cells"]
        row = list(cells[self.number(name, who) - 1])
        last = max(i + 1 for i, r in enumerate(cells) if any(r))
        while len(cells) < last:
            cells.append([])
        cells.insert(last, row)
        return last + 1


@pytest.fixture
def sheet(tmp_path, client):
    fake = FakeSheet(tmp_path)
    sheet_sync._transport = httpx.MockTransport(fake)
    assert client.put("/api/settings", json={"crm.sheet_secret": LINK}).status_code == 200   # pasting the link sets the tabs up
    jobs.drain()
    assert fake.actions == ["read"]
    fake.actions.clear()
    yield fake
    jobs.drain()
    sheet_sync._transport = None
    sheet_sync._synced_version = None


def book():
    """You, a colleague at your organization, a contact elsewhere, and someone you keep private."""
    me = store.set_me(name="Alex Rivera")
    cc = store.create_entity("organization", "Cinder Labs", attributes={"website": "https://cinderlabs.example"})
    store.create_edge(me.id, cc.id, "works_at")
    helio = store.create_entity("organization", "Helio Cold Chain", attributes={"location": "Portland, OR"}, tags=["partner"])
    priya = store.create_entity("person", "Priya Nair", summary="Runs pilots at Helio.",
                                attributes={"title": "Head of Pilots", "email": "priya@helio.example", "phone": "+1 503 555 0100"},
                                tags=["partner", "Cold Chain"])
    store.create_edge(priya.id, helio.id, "works_at")
    dan = store.create_entity("person", "Dan Rowe", attributes={"email": "dan@cinderlabs.example", "phone": "+15035550199"})
    store.create_edge(dan.id, cc.id, "works_at")
    store.create_entity("person", "Aunt May", tags=["family", "private"])
    return {"me": me, "cc": cc, "helio": helio, "priya": priya, "dan": dan}


def entity(name: str, kind: str = "person"):
    hits = [e for e in store.all_entities(kind) if e.name == name]
    assert len(hits) == 1, f"{len(hits)} records called {name}"
    return hits[0]


def employer(person_id: str) -> str | None:
    from modules.crm.server import snapshot
    from modules.crm.server.connections import build_index, current_org
    snap = snapshot.load()
    org = current_org(snap, build_index(snap), person_id)
    return org.name if org else None


# ── Filling the sheet ─────────────────────────────────────────────────

def test_pasting_the_link_sets_up_both_tabs_with_plain_text_columns(sheet):
    assert [s["name"] for s in sheet.state["sheets"]] == ["People", "Organizations"]   # the blank first tab is reused
    people = sheet.tab("People")
    assert sheet.headers("People") == ["Name", "Organization", "Title", "Email", "Phone", "LinkedIn", "Location", "Tags",
                                       "Summary", "Add a note", "Lodge ID"]
    assert sheet.headers("Organizations") == ["Name", "Website", "Location", "Email", "Tags", "Summary", "Add a note", "Lodge ID"]
    assert people["frozen"] == 1 and sorted(people["textCols"]) == list(range(1, 12))
    assert [p["description"] for p in people["protections"]] == ["The Lodge: Lodge ID"] and people["protections"][0]["warningOnly"]
    assert "Leave it blank" in people["notes"]["1:11"]
    assert capture.get_state("sheet")["spreadsheet"]["name"] == "Team contacts"


def test_the_first_sync_puts_everyone_on_except_you_and_anyone_private(sheet):
    b = book()
    sheet_sync.sync()

    assert [r["Name"] for r in sheet.rows("People")] == ["Dan Rowe", "Priya Nair"]
    priya = sheet.row("People", "Priya Nair")
    assert priya == {"Name": "Priya Nair", "Organization": "Helio Cold Chain", "Title": "Head of Pilots", "Email": "priya@helio.example",
                     "Phone": "+1 503 555 0100", "LinkedIn": "", "Location": "", "Tags": "partner, cold-chain",
                     "Summary": "Runs pilots at Helio.", "Add a note": "", "Lodge ID": b["priya"].id}
    assert [r["Name"] for r in sheet.rows("Organizations")] == ["Cinder Labs", "Helio Cold Chain"]
    assert sheet.row("Organizations", "Cinder Labs")["Website"] == "https://cinderlabs.example"
    assert capture.get_state("sheet")["last_counts"]["rows_added"] == 4


def test_a_second_sync_with_nothing_new_changes_nothing(sheet):
    book()
    sheet_sync.sync()
    before, version = json.dumps(sheet.state), store.version()
    sheet.actions.clear()
    sheet_sync.sync()
    assert sheet.actions == ["read"]                  # nothing to write
    assert json.dumps(sheet.state) == before and store.version() == version
    assert sheet_sync.seconds() == sheet_sync.EVERY_SECONDS


# ── Changes both ways ─────────────────────────────────────────────────

def test_a_change_on_the_sheet_comes_in_and_a_change_here_goes_out(sheet):
    b = book()
    sheet_sync.sync()
    sheet.set("People", "Priya Nair", "Title", "VP Operations")
    sheet.set("People", "Priya Nair", "Tags", "Partner,  Investor")
    store.update_entity(b["dan"].id, attributes={"email": "dan@cinderlabs.example", "phone": "+15035550142"})
    assert sheet_sync.seconds() == sheet_sync.SOON_SECONDS   # a change here goes out soon

    sheet_sync.sync()

    priya = store.get_entity(b["priya"].id)
    assert priya.attributes["title"] == "VP Operations" and priya.tags == ["partner", "investor"]
    assert sheet.row("People", "Dan Rowe")["Phone"] == "+15035550142"
    assert sheet.row("People", "Priya Nair")["Tags"] == "Partner,  Investor"   # same tags: the typing is left as it was
    assert sheet_sync.seconds() == sheet_sync.EVERY_SECONDS                  # what came in isn't sent back out


def test_a_cell_changed_on_both_sides_keeps_the_lodges_value_and_notes_the_sheets(sheet):
    b = book()
    sheet_sync.sync()
    sheet.set("People", "Priya Nair", "Title", "COO")
    store.update_entity(b["priya"].id, attributes={**b["priya"].attributes, "title": "Chief Operating Officer"})

    sheet_sync.sync()

    assert store.get_entity(b["priya"].id).attributes["title"] == "Chief Operating Officer"
    assert sheet.row("People", "Priya Nair")["Title"] == "Chief Operating Officer"
    [note] = store.notes_of(b["priya"].id)
    assert note.source == "sheet" and "Title was changed to “COO”" in note.body and "“Chief Operating Officer” was kept" in note.body


def test_a_cell_typed_over_while_the_lodge_was_writing_is_left_as_typed(sheet):
    b = book()
    sheet_sync.sync()
    store.update_entity(b["priya"].id, attributes={**b["priya"].attributes, "title": "Director"})
    sheet.between = lambda s: s.set("People", "Priya Nair", "Title", "Typed meanwhile")

    sheet_sync.sync()
    assert sheet.row("People", "Priya Nair")["Title"] == "Typed meanwhile"    # not written over

    sheet_sync.sync()                                                       # and then it's the newest change
    assert store.get_entity(b["priya"].id).attributes["title"] == "Typed meanwhile"


def test_changing_someones_organization_on_the_sheet_moves_their_job(sheet):
    b = book()
    sheet_sync.sync()
    sheet.set("People", "Priya Nair", "Organization", "Frostline Logistics")

    sheet_sync.sync()

    frostline = entity("Frostline Logistics", "organization")
    assert frostline.source == "sheet" and employer(b["priya"].id) == "Frostline Logistics"
    old = store.find_edge(b["priya"].id, b["helio"].id, "works_at")
    assert old.ended_at is not None                                          # the job the sheet showed has ended
    assert sheet.row("Organizations", "Frostline Logistics")["Lodge ID"] == frostline.id

    sheet.set("People", "Dan Rowe", "Organization", "cinder labs")       # the same organization, typed differently
    sheet_sync.sync()
    assert employer(b["dan"].id) == "Cinder Labs" and len(store.all_entities("organization")) == 3


# ── New rows and notes ────────────────────────────────────────────────

def test_a_new_row_becomes_a_new_person_with_their_organization(sheet):
    book()
    sheet_sync.sync()
    sheet.add("People", {"Name": "Tom Albright", "Organization": "Frostline Logistics", "Email": "tom@frostline.example",
                         "Phone": "007 123", "Tags": "Fleet, prospect", "Add a note": "Wants 50 trucks by spring."})

    sheet_sync.sync()

    tom = entity("Tom Albright")
    assert tom.source == "sheet" and tom.tags == ["fleet", "prospect"] and tom.attributes["phone"] == "007 123"
    assert employer(tom.id) == "Frostline Logistics"
    assert [n.body for n in store.notes_of(tom.id)] == ["Wants 50 trucks by spring."]
    row = sheet.row("People", "Tom Albright")
    assert row["Lodge ID"] == tom.id and row["Add a note"] == "" and row["Phone"] == "007 123"
    assert capture.get_state("sheet")["last_counts"]["new"] == 1


def test_a_new_row_for_someone_already_here_joins_their_record(sheet):
    b = book()
    sheet_sync.sync()
    sheet.delete("People", "Priya Nair")            # someone took her row off, then added her again by another name
    sheet.add("People", {"Name": "P. Nair", "Email": "PRIYA@helio.example", "LinkedIn": "https://www.linkedin.com/in/priyanair/"})

    sheet_sync.sync()

    assert len(store.all_entities("person")) == 4                           # nobody new
    priya = store.get_entity(b["priya"].id)
    assert priya.attributes["linkedin_url"] == "https://www.linkedin.com/in/priyanair/"   # a gap, filled
    assert priya.attributes["title"] == "Head of Pilots"                    # nothing else touched
    rows = [r for r in sheet.rows("People") if r["Lodge ID"] == priya.id]
    assert len(rows) == 1 and rows[0]["Name"] == "Priya Nair" and rows[0]["Title"] == "Head of Pilots"


def test_someone_added_twice_ends_up_on_one_row(sheet):
    b = book()
    sheet_sync.sync()
    sheet.add("People", {"Name": "Priya Nair", "Location": "Portland", "Add a note": "Met again at OEN."})

    sheet_sync.sync()

    assert [r["Name"] for r in sheet.rows("People")].count("Priya Nair") == 1
    priya = store.get_entity(b["priya"].id)
    assert priya.attributes["location"] == "Portland" and [n.body for n in store.notes_of(priya.id)] == ["Met again at OEN."]


def test_a_copied_row_renamed_for_someone_new_becomes_a_new_record(sheet):
    b = book()
    sheet_sync.sync()
    row = sheet.copy_row("People", "Priya Nair")
    sheet.put("People", row, "Name", "Ravi Nair")

    sheet_sync.sync()

    ravi = entity("Ravi Nair")
    assert ravi.id != b["priya"].id and ravi.attributes["email"] == "priya@helio.example"   # what they copied came along
    assert sheet.row("People", "Ravi Nair")["Lodge ID"] == ravi.id
    assert sheet.row("People", "Priya Nair")["Lodge ID"] == b["priya"].id


def test_a_note_is_filed_once_and_the_cell_emptied(sheet):
    b = book()
    sheet_sync.sync()
    sheet.set("People", "Dan Rowe", "Add a note", "Moving to Boise in May.")
    sheet_sync.sync()
    assert [n.body for n in store.notes_of(b["dan"].id)] == ["Moving to Boise in May."]
    assert sheet.row("People", "Dan Rowe")["Add a note"] == ""

    sheet.set("People", "Dan Rowe", "Add a note", "Moving to Boise in May.")   # say emptying it hadn't worked
    sheet_sync.sync()
    assert len(store.notes_of(b["dan"].id)) == 1


def test_a_half_typed_row_without_a_name_is_left_alone(sheet):
    book()
    sheet_sync.sync()
    sheet.add("People", {"Email": "someone@example.com"})
    sheet_sync.sync()
    assert len(store.all_entities("person")) == 4
    assert any(r["Email"] == "someone@example.com" and not r["Lodge ID"] for r in sheet.rows("People"))


# ── Slips on the sheet, and removals ──────────────────────────────────

def test_a_deleted_row_comes_back_and_a_deleted_record_leaves(sheet):
    b = book()
    sheet_sync.sync()
    sheet.delete("People", "Priya Nair")
    store.delete_entity(b["dan"].id)

    sheet_sync.sync()

    assert store.get_entity(b["priya"].id) is not None
    assert [r["Name"] for r in sheet.rows("People")] == ["Priya Nair"]


def test_tagging_someone_private_takes_them_off(sheet):
    b = book()
    sheet_sync.sync()
    sheet.set("People", "Dan Rowe", "Tags", "private")     # from the sheet
    store.update_entity(b["priya"].id, tags=["partner", "private"])   # or here
    sheet_sync.sync()
    assert sheet.rows("People") == []
    assert "private" in store.get_entity(b["dan"].id).tags


def test_a_deleted_column_comes_back_without_emptying_anything(sheet):
    b = book()
    sheet_sync.sync()
    people = sheet.tab("People")
    col = people["cells"][0].index("Email")
    for row in people["cells"]:
        if len(row) > col:
            row.pop(col)

    sheet_sync.sync()

    assert store.get_entity(b["priya"].id).attributes["email"] == "priya@helio.example"
    assert sheet.headers("People")[-1] == "Email" and sheet.row("People", "Priya Nair")["Email"] == "priya@helio.example"


def test_columns_the_lodge_doesnt_know_are_left_alone(sheet):
    b = book()
    sheet_sync.sync()
    people = sheet.tab("People")
    people["cells"][0].append("Met at")
    sheet.set("People", "Priya Nair", "Met at", "OEN showcase")
    store.update_entity(b["priya"].id, summary="Runs pilots and fleets at Helio.")
    sheet_sync.sync()
    row = sheet.row("People", "Priya Nair")
    assert row["Met at"] == "OEN showcase" and row["Summary"] == "Runs pilots and fleets at Helio."


def many(sheet):
    for i in range(12):
        p = store.create_entity("person", f"Person {i:02}", attributes={"email": f"p{i}@example.com"})
        store.create_edge(p.id, store.create_entity("organization", f"Org {i:02}").id, "works_at")
    sheet_sync.sync()
    for i in range(12):
        sheet.set("People", f"Person {i:02}", "Email", "")


def test_a_column_emptied_all_at_once_waits_for_you(sheet):
    many(sheet)
    sheet_sync.sync()

    assert all(e.attributes.get("email") for e in store.all_entities("person"))
    held = capture.get_state("sheet")["held"]
    assert held == {"People": {"cells": 12, "columns": ["Email"]}}
    assert all(r["Email"] == "" for r in sheet.rows("People"))             # and the sheet isn't put back on its own

    sheet_sync.decide("restore")
    sheet_sync.sync()
    assert all(r["Email"] for r in sheet.rows("People"))
    assert "held" not in capture.get_state("sheet") and "decision" not in capture.get_state("sheet")


def test_you_can_take_a_mass_change_from_the_sheet(sheet):
    many(sheet)
    sheet_sync.sync()
    sheet_sync.decide("apply")
    sheet_sync.sync()
    assert not any(e.attributes.get("email") for e in store.all_entities("person"))
    assert "held" not in capture.get_state("sheet")


# ── The link ──────────────────────────────────────────────────────────

def test_problems_with_the_link_are_kept_for_settings(sheet):
    sheet.answer = httpx.Response(200, text="<html>Sign in - Google Accounts</html>", headers={"content-type": "text/html"})
    sheet_sync.sync()
    state = capture.get_state("sheet")
    assert state["link_problem"] and "Who has access “Anyone”" in state["error"]

    sheet.answer = httpx.Response(200, json={"ok": True, "version": 0})
    sheet_sync.sync()
    assert "older than this version" in capture.get_state("sheet")["error"]

    sheet.answer = None
    sheet_sync.sync()
    assert "error" not in capture.get_state("sheet") and "link_problem" not in capture.get_state("sheet")


def test_the_test_link_and_other_addresses_are_explained(sheet):
    for link, says in [("https://script.google.com/macros/s/AKfyc/dev", "test link"), ("https://example.com/exec", "isn't an Apps Script")]:
        settings.update({"crm.sheet_secret": link})
        with pytest.raises(sheet_sync.SheetError, match=says):
            sheet_sync.test()
    jobs.drain()


def test_settings_api(client, sheet):
    assert client.get("/api/crm/sheet/script").json()["text"].startswith("/** @OnlyCurrentDoc */")
    r = client.post("/api/crm/sheet/test")
    assert r.status_code == 200 and r.json()["spreadsheet"]["name"] == "Team contacts"
    status = client.get("/api/crm/sheet").json()
    assert status["configured"] and status["last_ok_at"] and status["script_version"] == sheet_script.VERSION
    assert client.post("/api/crm/sheet/sync").status_code == 202
    assert client.post("/api/crm/sheet/decide", json={"choice": "restore"}).status_code == 202
    assert client.post("/api/crm/sheet/decide", json={"choice": "nope"}).status_code == 422
    jobs.drain()
    assert client.get("/api/settings").json()["values"]["crm.sheet_secret"] == ""   # the link is kept like a key


def test_no_link_no_sync():
    assert sheet_sync.seconds() == 0
    assert sheet_sync.sync() == {"skipped": "no link"}
