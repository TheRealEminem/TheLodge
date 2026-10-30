"""The "people.dossier" offer and the CRM's part of the people directory (dossier.py)."""
import pytest
from crm_helpers import link, make

from core.server import family
from modules.crm.server import dossier

TRANSCRIPT = """Meeting: Pilot review

## Notes from granola
They reviewed the Frostline pilot.

## Transcript
Me: How did the Frostline pilot go for you?
Them: Honestly Frostline was slow to answer, but the trucks themselves worked well.
Me: And Lumen Labs?
Them: I really like what you're building at Lumen Labs. Keep me posted."""


@pytest.fixture
def book(client):
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    me = client.get("/api/crm/me").json()
    lumen = make(client, "organization", "Lumen Labs")
    link(client, me, "works_at", lumen)
    priya = make(client, "person", "Priya Nair", summary="Runs pilots at Helio.", attributes={"email": "priya@helio.example"})
    frost = make(client, "organization", "Frostline Logistics", attributes={"aliases": ["Frostline"]})
    review = make(client, "meeting", "Pilot review", occurred_at="2026-09-14T15:00:00Z",
                  attributes={"key_points": ["The pilot ran 50 trucks", "Frostline was slow"]})
    link(client, priya, "attended", review)
    link(client, me, "attended", review)
    client.post(f"/api/crm/entities/{review['id']}/notes", json={"body": TRANSCRIPT, "occurred_at": "2026-09-14T15:00:00Z"})
    client.post(f"/api/crm/entities/{priya['id']}/notes",
                json={"body": "Said Frostline's pricing felt steep for a pilot.", "occurred_at": "2026-08-02T10:00:00Z"})
    return {"me": me, "priya": priya, "frost": frost, "lumen": lumen, "review": review}


def ask(person, **args):
    return family.call(dossier.OFFER, id=f"crm:{person['id']}", **args)


def test_the_offer_is_answered_in_this_app_with_the_records_and_key_points(client, book):
    d = ask(book["priya"], scale="cloud")
    assert d["ref"] == f"crm:{book['priya']['id']}" and d["name"] == "Priya Nair" and d["first"] == "Priya"
    assert "Runs pilots at Helio." in d["records"] and d["material"]
    assert "2026-09-14, Pilot review: The pilot ran 50 trucks; Frostline was slow" in d["key_points"]
    assert d["company"] == {"ref": f"crm:{book['lumen']['id']}", "name": "Lumen Labs"}
    assert d["owner"].startswith("The owner is Alex Rivera") and d["meetings_with_you"] == 1
    assert d["passages"] == [] and d["voice"] == []        # no subject asked about, no voice asked for


def test_passages_mention_the_subject_from_notes_and_transcripts(client, book):
    d = ask(book["priya"], about={"ref": f"crm:{book['frost']['id']}"}, scale="cloud")
    assert d["subject"]["name"] == "Frostline Logistics" and d["subject"]["kind"] == "organization"
    sources = [p["source"] for p in d["passages"]]
    assert "Your notes on them" in sources and any("transcript" in s for s in sources)
    assert any("slow to answer" in p["text"] for p in d["passages"])
    assert [p["date"] for p in d["passages"]] == sorted((p["date"] for p in d["passages"]), reverse=True)

    quiet = ask(book["priya"], about={"ref": f"crm:{book['frost']['id']}"}, scale="cloud", transcripts=False)
    assert not any("slow to answer" in p["text"] for p in quiet["passages"])    # the transcript was left out
    assert any("pricing felt steep" in p["text"] for p in quiet["passages"])


def test_a_product_is_found_by_its_name_and_other_names(client, book):
    d = ask(book["priya"], about={"kind": "product", "name": "Coldbox", "terms": ["Lumen Labs"], "summary": "Our sensor"},
            scale="local")
    assert d["subject"] == {"kind": "product", "name": "Coldbox", "summary": "Our sensor"}
    assert any("really like what you're building" in p["text"] for p in d["passages"])


def test_toward_you_it_is_what_they_said_in_meetings_with_you(client, book):
    d = ask(book["priya"], about={"kind": "me"}, scale="cloud")
    assert d["subject"]["kind"] == "me"
    [p] = d["passages"]
    assert p["source"] == "What they said in “Pilot review”" and "Keep me posted" in p["text"]
    assert "How did the Frostline pilot go" not in p["text"]      # your own lines aren't theirs


def test_their_own_lines_are_their_voice_in_a_one_to_one(client, book):
    d = ask(book["priya"], voice=True, scale="cloud")
    assert [v["text"] for v in d["voice"]][-1] == "I really like what you're building at Lumen Labs. Keep me posted."
    other = make(client, "person", "Sam Ortiz")
    link(client, other, "attended", book["review"])                # now it isn't just the two of you
    assert ask(book["priya"], voice=True, scale="cloud")["voice"] == []


def test_caps_hold_per_scale(client, book):
    long = " ".join(["Frostline came up again in the long notes."] * 2_000)
    client.post(f"/api/crm/entities/{book['priya']['id']}/notes", json={"body": long})
    local = ask(book["priya"], about={"ref": f"crm:{book['frost']['id']}"}, scale="local")
    cloud = ask(book["priya"], about={"ref": f"crm:{book['frost']['id']}"}, scale="cloud")
    assert sum(len(p["text"]) for p in local["passages"]) <= dossier.PASSAGES["local"]
    assert sum(len(p["text"]) for p in cloud["passages"]) > sum(len(p["text"]) for p in local["passages"])


def test_fingerprint_changes_with_what_is_on_file(client, book):
    first = ask(book["priya"], about={"kind": "me"})["fingerprint"]
    assert ask(book["priya"], about={"kind": "me"})["fingerprint"] == first
    client.post(f"/api/crm/entities/{book['priya']['id']}/notes", json={"body": "Moved to Lisbon."})
    assert ask(book["priya"], about={"kind": "me"})["fingerprint"] != first


def test_you_and_strangers_are_refused_and_merges_are_followed(client, book):
    with pytest.raises(ValueError):
        ask(book["me"])
    with pytest.raises(LookupError):
        family.call(dossier.OFFER, id="crm:nobody")
    twin = make(client, "person", "Priya N.")
    assert client.post(f"/api/crm/entities/{twin['id']}/merge", json={"into_id": book["priya"]["id"]}).status_code == 200
    assert ask(twin)["ref"] == f"crm:{book['priya']['id']}"


def test_people_directory_finds_crm_people(client, book):
    found = client.get("/api/people", params={"q": "pri"}).json()["people"]
    assert [p["ref"] for p in found] == [f"crm:{book['priya']['id']}"]
    assert found[0]["email"] == "priya@helio.example"
    everyone = client.get("/api/people", params={"q": ""}).json()["people"]
    assert everyone[0]["ref"] == "core:me"
