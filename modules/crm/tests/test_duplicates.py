"""Likely duplicates are flagged, never merged by themselves; a merge you OK keeps everything and can be undone."""
from core.server import db, jobs
from crm_helpers import link, make

from modules.crm.server import exporting, store


def check(client):
    assert client.post("/api/crm/duplicates/check").status_code == 202
    jobs.drain()
    return client.get("/api/crm/duplicates").json()


def names(page):
    return sorted(tuple(sorted((p["a"]["name"], p["b"]["name"]))) for p in page["items"])


def test_likely_pairs_are_flagged_with_reasons_and_nothing_is_merged(client):
    make(client, "person", "Bob Lee")
    make(client, "person", "Robert Lee")
    make(client, "person", "Rob Stone")
    make(client, "person", "Ana Ruiz", attributes={"email": "ana@helio.example"})
    make(client, "person", "Ana R. Ruiz-Diaz", attributes={"email": "ANA@helio.example"})
    make(client, "person", "Jordon Reyes")
    make(client, "person", "Jordan Reyes")
    make(client, "organization", "Helio Inc.")
    make(client, "organization", "Helio")
    make(client, "organization", "Oak Foundation")
    make(client, "organization", "Gates Foundation")
    page = check(client)
    assert names(page) == [("Ana R. Ruiz-Diaz", "Ana Ruiz"), ("Bob Lee", "Robert Lee"), ("Helio", "Helio Inc."),
                           ("Jordan Reyes", "Jordon Reyes")]
    reasons = {p["a"]["name"] + "/" + p["b"]["name"]: p["reasons"] for p in page["items"]}
    assert any("Same email" in r for rs in reasons.values() for r in rs)
    assert db.one("SELECT count(*) AS n FROM crm_entities WHERE kind = 'person'")["n"] == 7   # all still there


def test_a_first_name_alone_is_only_flagged_with_something_shared(client):
    priya, full = make(client, "person", "Priya"), make(client, "person", "Priya Nair")
    make(client, "person", "Priya Shah")
    assert names(check(client)) == []
    meeting = make(client, "meeting", "Pilot call")
    link(client, priya, "attended", meeting)
    link(client, full, "attended", meeting)
    assert names(check(client)) == [("Priya", "Priya Nair")]


def test_not_the_same_stays_that_way(client):
    make(client, "person", "Sam Ortiz")
    make(client, "person", "Samantha Ortiz")
    pair = check(client)["items"][0]
    assert client.post(f"/api/crm/duplicates/{pair['id']}/not-same").status_code == 200
    assert check(client)["items"] == []
    assert db.one("SELECT status FROM crm_duplicates WHERE id = ?", (pair["id"],))["status"] == "not_same"


def test_a_merge_keeps_everything_old_links_follow_it_and_undo_splits_them_again(client):
    keep = make(client, "person", "Jordan Reyes", attributes={"title": "Head of Fleet"}, tags=["fleet"])
    gone = make(client, "person", "Jordan Reyes ", attributes={"email": "jordan@frostline.example", "location": "Portland"},
                summary="Runs fleet operations.", tags=["portland"])
    org, meeting = make(client, "organization", "Frostline"), make(client, "meeting", "Depot walk-through")
    link(client, gone, "works_at", org)
    link(client, keep, "works_at", org)          # the same edge on both: folded into one
    link(client, gone, "attended", meeting)
    client.post(f"/api/crm/entities/{gone['id']}/notes", json={"body": "Prefers mornings."})
    pair = check(client)["items"][0]

    kept = client.post(f"/api/crm/duplicates/{pair['id']}/merge", json={"keep_id": keep["id"]}).json()
    assert kept["id"] == keep["id"]
    assert client.get(f"/api/crm/entities/{gone['id']}").status_code == 404
    merged = store.get_entity(keep["id"])
    assert merged.summary == "Runs fleet operations." and merged.attributes["email"] == "jordan@frostline.example"
    assert sorted(merged.tags) == ["fleet", "portland"]
    assert [n.body for n in store.notes_of(keep["id"])] == ["Prefers mornings."]
    assert store.describe(gone["id"])["href"] == f"#/crm/e/{keep['id']}"       # a link to the old record still lands
    assert client.get(f"/api/crm/entities/{gone['id']}/moved").json()["id"] == keep["id"]
    in_export = [m for m in exporting.export()["merges"] if m["source_id"] == gone["id"]]   # the JSON export keeps it
    assert len(in_export) == 1 and in_export[0]["snapshot"]["source"]["summary"] == "Runs fleet operations."

    merge = client.get(f"/api/crm/entities/{keep['id']}/merges").json()[0]
    assert merge["name"] == "Jordan Reyes " or merge["name"].strip() == "Jordan Reyes"
    back = client.post(f"/api/crm/merges/{merge['id']}/undo").json()
    assert back["id"] == gone["id"]
    restored, kept = store.get_entity(gone["id"]), store.get_entity(keep["id"])
    assert restored.summary == "Runs fleet operations." and restored.attributes["location"] == "Portland"
    assert kept.summary is None and "email" not in kept.attributes and kept.tags == ["fleet"]
    assert [n.body for n in store.notes_of(gone["id"])] == ["Prefers mornings."] and store.notes_of(keep["id"]) == []
    edges = {(r["source_id"], r["kind"], r["target_id"]) for r in db.query("SELECT * FROM crm_relationships")}
    assert {(gone["id"], "works_at", org["id"]), (keep["id"], "works_at", org["id"]), (gone["id"], "attended", meeting["id"])} <= edges
    assert client.get(f"/api/crm/entities/{keep['id']}/merges").json() == []
    assert check(client)["items"] == []                                       # you split them: not flagged again
    assert client.post(f"/api/crm/merges/{merge['id']}/undo").status_code == 422


def test_merging_from_a_profile_can_be_undone_too_and_keeps_you_as_you(client):
    me = client.put("/api/crm/me", json={"name": "Alex Rivera"}).json()
    other = make(client, "person", "Sam M.")
    client.post(f"/api/crm/entities/{me['id']}/merge", json={"into_id": other["id"]})
    assert store.get_me().id == other["id"]
    merge = client.get(f"/api/crm/entities/{other['id']}/merges").json()[0]
    client.post(f"/api/crm/merges/{merge['id']}/undo")
    assert store.get_me().id == me["id"]
