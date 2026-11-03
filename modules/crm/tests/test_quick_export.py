"""Quick export (quick_export.py): one person or organization as Markdown to copy, or saved as Markdown or PDF."""
import pytest
from crm_helpers import link, make

from core.server import db


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    me = client.get("/api/crm/me").json()
    helio = make(client, "organization", "Helio Cold Chain", attributes={"website": "helio.example"})
    priya = make(client, "person", "Priya Nair", summary="Runs pilots at Helio.",
                 attributes={"title": "CEO", "email": "priya@helio.example", "phone": "+1 555 0100",
                             "linkedin_url": "linkedin.com/in/priya-example", "location": "Oakland"}, tags=["pilot"])
    link(client, priya, "works_at", helio)
    client.put(f"/api/crm/people/{priya['id']}/connection", json={"strength": 4})
    review = make(client, "meeting", "Pilot review", occurred_at="2026-09-14T15:00:00Z", summary="The pilot hit its targets.")
    link(client, priya, "attended", review)
    link(client, me, "attended", review)
    client.post(f"/api/crm/entities/{priya['id']}/notes", json={"body": "Wants an intro to Frostline."})
    client.post(f"/api/crm/entities/{priya['id']}/notes", json={"body": "Long report. " + "Cold chain history. " * 300})
    db.execute("INSERT INTO crm_overviews (id, entity_id, body, fingerprint, written_by, created_at) VALUES (?, ?, ?, '', ?, ?)",
               (db.new_id(), priya["id"], "Priya runs Helio and wants a Frostline intro.", "Ollama (qwen)", "2026-10-01T00:00:00Z"))
    return {"me": me, "helio": helio, "priya": priya, "review": review}


def export(client, entity):
    r = client.get(f"/api/crm/entities/{entity['id']}/export")
    assert r.status_code == 200, r.text
    return r.json()


def test_a_person_comes_out_as_markdown_without_their_email_or_phone(client, book):
    out = export(client, book["priya"])
    md = out["markdown"]
    assert out["title"] == "Priya Nair" and md.startswith("# Priya Nair\n\nCEO at Helio Cold Chain · Oakland")
    for part in ("[LinkedIn](https://linkedin.com/in/priya-example)", "## How you know them", "Your rating: 4 of 5",
                 "## Overview\nPriya runs Helio and wants a Frostline intro.", "## About\nRuns pilots at Helio.", "## Tags\npilot",
                 "- Helio Cold Chain: ", "2026-09-14 · Pilot review (you were there): The pilot hit its targets.",
                 "Wants an intro to Frostline.", "cut for length", "Email addresses and phone numbers are left out"):
        assert part in md, part
    assert "priya@helio.example" not in md and "555 0100" not in md
    assert out["characters"] == len(md) < 60_000


def test_an_organization_lists_its_people(client, book):
    md = export(client, book["helio"])["markdown"]
    assert md.startswith("# Helio Cold Chain") and "## People there" in md and "Priya Nair" in md
    assert "[Website](https://helio.example)" in md


def test_only_people_and_organizations(client, book):
    assert client.get(f"/api/crm/entities/{book['review']['id']}/export").status_code == 422
    assert client.get("/api/crm/entities/nobody/export").status_code == 404
    assert export(client, book["me"])["markdown"].startswith("# Alex Rivera")          # your own record is fine too


def test_saved_as_markdown_or_pdf_in_the_exports_folder(client, book):
    for fmt, magic in (("md", b"# Priya Nair"), ("pdf", b"%PDF")):
        r = client.post(f"/api/crm/entities/{book['priya']['id']}/export", json={"format": fmt})
        assert r.status_code == 200, r.text
        saved = r.json()
        assert saved["name"].startswith("Priya Nair ") and saved["name"].endswith(f".{fmt}") and "crm/exports" in saved["folder"]
        got = client.get(f"/api/crm/exports/{saved['name']}")
        assert got.status_code == 200 and got.content.startswith(magic)
    assert client.post(f"/api/crm/entities/{book['priya']['id']}/export", json={"format": "docx"}).status_code == 422
    assert client.get("/api/crm/exports/..%2F..%2Flodge.db").status_code == 404
