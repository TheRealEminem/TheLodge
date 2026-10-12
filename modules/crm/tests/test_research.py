"""Research flags: who has nothing on file, the brief, and bringing a report back through the inbox.

The AI is a fake (conftest's fake_structured), so these check what the app does with an answer, not the answer."""
import pytest
from crm_helpers import entity, extraction, link, make, post_notes

REPORT = ("Jordan Reyes is a supply chain operator. " + "Background and history of the work in cold chain. " * 40)


def flagged(client, state="needed"):
    return [r["person"]["name"] for r in client.get("/api/crm/research", params={"state": state}).json()["items"]]


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera", "title": "Founder"})
    return {"nothing": make(client, "person", "Jordan Reyes"),
            "summary": make(client, "person", "Priya Nair", summary="CEO of Helio."),
            "first": make(client, "person", "Cher")}


def test_someone_with_nothing_on_file_is_flagged_and_you_are_not(client, book):
    assert flagged(client) == ["Jordan Reyes"]            # Priya has a summary, Cher has no surname, you are you
    assert client.get("/api/crm/research", params={"state": "name_needed"}).json()["total"] == 1


def test_a_long_note_or_a_short_one_changes_the_flag_differently(client, book):
    jordan = book["nothing"]["id"]
    client.post(f"/api/crm/entities/{jordan}/notes", json={"body": "Met at the depot."})
    assert flagged(client) == ["Jordan Reyes"]            # a short note is not research
    client.post(f"/api/crm/entities/{jordan}/notes", json={"body": REPORT})
    assert flagged(client) == []


def test_a_document_filed_about_them_counts(client, book):
    doc = make(client, "document", "Jordan profile")
    link(client, book["nothing"], "about", doc)
    assert flagged(client) == []


def test_snooze_dismiss_and_bring_it_back(client, book):
    jordan = book["nothing"]["id"]
    assert client.post(f"/api/crm/people/{jordan}/research", json={"action": "snooze", "days": 7}).json()["state"] == "snoozed"
    assert flagged(client) == [] and flagged(client, "snoozed") == ["Jordan Reyes"]
    assert client.post(f"/api/crm/people/{jordan}/research", json={"action": "dismiss"}).json()["state"] == "dismissed"
    assert client.post(f"/api/crm/people/{jordan}/research", json={"action": "restore"}).json()["state"] == "needed"
    assert flagged(client) == ["Jordan Reyes"]


def test_a_snooze_that_has_run_out_flags_them_again(client, book):
    jordan = book["nothing"]
    client.patch(f"/api/crm/entities/{jordan['id']}", json={"attributes": {"research": {"status": "snoozed", "until": "2020-01-01T00:00:00Z"}}})
    assert flagged(client) == ["Jordan Reyes"]


def test_you_cannot_flag_yourself(client, book):
    me = client.get("/api/crm/me").json()
    assert client.post(f"/api/crm/people/{me['id']}/research", json={"action": "snooze"}).status_code == 422
    assert client.get(f"/api/crm/people/{me['id']}/research/brief").status_code == 422


def test_the_people_list_filters_to_the_flagged_and_counts_them(client, book):
    page = client.get("/api/crm/people", params={"needs_research": "true"}).json()
    assert [r["person"]["name"] for r in page["items"]] == ["Jordan Reyes"] and page["items"][0]["needs_research"]
    assert page["needs_research"] == 1
    assert client.get("/api/crm/people").json()["needs_research"] == 1       # the count ignores the filter


def test_the_home_page_lists_the_ones_who_matter_most_first(client, book):
    close = make(client, "person", "Dana Okafor")
    assert client.put(f"/api/crm/people/{close['id']}/connection", json={"strength": 5}).status_code == 200
    dash = client.get("/api/crm/dashboard").json()
    assert [r["person"]["name"] for r in dash["research"]] == ["Dana Okafor", "Jordan Reyes"]
    assert dash["research_needed"] == 2 and dash["research_close"] == 1


def test_the_brief_names_what_we_know_and_leaves_the_email_address_out(client, book):
    jordan = book["nothing"]
    org = make(client, "organization", "Frostline Logistics")
    client.patch(f"/api/crm/entities/{jordan['id']}", json={"attributes": {
        "title": "Head of Fleet", "email": "jordan@frostline.example", "location": "Portland",
        "linkedin_url": "linkedin.com/in/jordanreyes"}})
    link(client, jordan, "works_at", org)
    meeting = make(client, "meeting", "Depot walk-through", occurred_at="2026-03-04T10:00:00Z")
    link(client, jordan, "attended", meeting)
    text = client.get(f"/api/crm/people/{jordan['id']}/research/brief").json()["text"]
    for expected in ("Jordan Reyes", "Head of Fleet at Frostline Logistics", "Portland", "frostline.example",
                     "https://linkedin.com/in/jordanreyes", "Depot walk-through", "Alex Rivera", "Sources"):
        assert expected in text, expected
    assert "jordan@frostline.example" not in text


def test_a_first_name_alone_gets_no_brief(client, book):
    r = client.get(f"/api/crm/people/{book['first']['id']}/research/brief")
    assert r.status_code == 422 and "surname" in r.json()["detail"]


def test_a_report_filed_on_someone_attaches_to_them_clears_the_flag_and_goes_through_review(client, book, fake_structured):
    jordan = book["nothing"]
    # The reader finds a different spelling and a stranger; the person you named is still the subject.
    fake_structured.reply = extraction([entity("p1", "Jordan Reyes", role="mentioned", title="Head of Fleet", summary="Runs fleet operations."),
                                       entity("o1", "Frostline Logistics", kind="organization")],
                                       doc_type="meeting_notes", subject_ref=None)
    job = post_notes(client, REPORT, subject_id=jordan["id"])
    assert job["status"] == "review" and job["proposal"]["doc_type"] == "person_profile"
    subject = next(e for e in job["proposal"]["entities"] if e["role"] == "subject")
    assert subject["match_id"] == jordan["id"] and subject["action"] == "link" and not subject["ambiguous"]
    assert "research about Jordan Reyes" in fake_structured.calls[0]["prompt"]
    assert flagged(client) == ["Jordan Reyes"]                 # not until you apply it

    r = client.post(f"/api/crm/ingest/jobs/{job['id']}/apply", json={"proposal": job["proposal"]})
    assert r.status_code == 200 and r.json()["result"]["subject_id"] == jordan["id"]
    assert flagged(client) == []
    person = client.get(f"/api/crm/entities/{jordan['id']}").json()["entity"]
    assert person["summary"] == "Runs fleet operations." and person["attributes"]["title"] == "Head of Fleet"
    assert any(len(n["body"]) > 1500 for n in client.get(f"/api/crm/entities/{jordan['id']}/notes").json())


def test_a_report_read_by_rules_alone_still_lands_on_them(client, book):
    from core.server import settings
    settings.update({"crm.extraction_provider": "rules", "crm.utility_provider": "rules"})
    jordan = book["nothing"]
    # Rules find nobody by name and a short report has no summary: applying it still counts as the research.
    job = post_notes(client, "Short note on file about the depot lead. " * 8, subject_id=jordan["id"])
    subject = next(e for e in job["proposal"]["entities"] if e["role"] == "subject")
    assert subject["match_id"] == jordan["id"]
    client.post(f"/api/crm/ingest/jobs/{job['id']}/apply", json={"proposal": job["proposal"]})
    assert client.get(f"/api/crm/people/{jordan['id']}/research").json()["state"] == "has_context"


def test_a_report_for_someone_who_is_gone_is_refused(client, book):
    r = client.post("/api/crm/ingest/notes", json={"text": REPORT, "subject_id": "nobody"})
    assert r.status_code == 422
