"""Putting right what an import got wrong: names that only look alike, a source on the wrong person, words the AI wrote
about someone. And hats: who's in one, and meetings coming in from Trailmix under theirs."""
from core.server import jobs

from modules.crm.server import hats, ingest, resolve, store

from crm_helpers import entity, extraction, link, make
from test_capture import me  # noqa: F401 - a fixture


def proposal_row(client, fake_structured, ents, text="Dana gave the harbor update.", **extra):
    fake_structured.reply = extraction(ents)
    r = client.post("/api/crm/ingest/meeting", json={"origin": "trailmix", "external_id": extra.pop("uid", "tm-1"), "title": "Committee chairs",
                                                     "started_at": "2026-10-01T17:00:00Z", "notes": text, **extra})
    assert r.status_code == 202, r.text
    jobs.drain()
    return client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()


# ── Names ─────────────────────────────────────────────────────────────

def test_names_that_only_look_alike_do_not_link():
    fit = lambda kind, a, b: resolve.name_fit(kind, a, b)  # noqa: E731
    assert fit("person", "Serena Holt", "John Holt") == "different"
    assert fit("person", "Sean Hale", "Shannon Hale") == "different"
    assert fit("person", "Brian Hollis", "Don Hollister") == "different"
    assert fit("person", "Eric Lindqvist", "Erik Lindqvist") == "same"
    assert fit("person", "Kacy Brandvold", "Kacey Brandvolt") == "same"
    assert fit("person", "Eli Marsh-Okafor", "Elijah Marsh-Okafor") == "same"
    assert fit("person", "Dana", "Dana Whitfield") == "partial"
    assert fit("person", "Noah", "Sarah Nolan") == "different"
    assert fit("organization", "Cascade Wild", "Summit Cascade") == "different"
    assert fit("organization", "Ames Family Foundation", "Harbor Foundation") == "different"
    assert fit("organization", "Northfield University", "Riverton State University") == "different"
    assert fit("organization", "Kellan Trust", "Kellan Trust USA") == "same"
    assert fit("organization", "Harbor Entrepreneurs Network", "Harbor Entrepreneurship Network") == "same"


def test_a_surname_the_source_never_gave_is_taken_off():
    assert resolve.as_written("Dana Whitfield", "Dana gave the update.") == "Dana"
    assert resolve.as_written("Dana Whitfield", "Her role model is Dana Whitfield.") == "Dana Whitfield"
    assert resolve.as_written("Dr. Whitfield", "Nothing about them.") == "Dr. Whitfield"


def test_a_first_name_alone_waits_for_you_instead_of_joining_a_stranger(client, fake_structured, me):
    whitfield = make(client, "person", "Dana Whitfield")
    row = proposal_row(client, fake_structured, [entity("p1", "Dana Whitfield", role="attendee", facts=["Gave the harbor update."])])
    assert row["status"] == "review"
    ent = next(e for e in row["proposal"]["entities"] if e["ref"] == "p1")
    assert ent["name"] == "Dana" and ent["ambiguous"] and ent["match_id"] is None
    assert ent["candidates"][0]["id"] == whitfield["id"]


def test_a_first_name_links_when_its_the_one_person_by_that_name_in_this_hat(client, fake_structured, me):
    hat = hats.create("Parks Board")
    chad = make(client, "person", "Theo Marsh")
    make(client, "person", "Theo Elsewhere")
    hats.place(hat, [chad["id"]], "you")
    fake_structured.reply = extraction([entity("p1", "Theo", role="attendee")])
    made, _ = ingest.create_meeting_job(origin="trailmix", external_id="tm-2", title="Parks", started_at="2026-10-01T17:00:00Z", notes="Theo presented.", hat_id=hat)
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{made['id']}").json()
    assert row["status"] == "applied"
    assert next(e for e in row["proposal"]["entities"] if e["ref"] == "p1")["match_id"] == chad["id"]
    assert row["result"]["record_id"] in {e.id for e in store.all_entities("meeting")}
    assert hats.source_hat(row["result"]["record_id"]) == hat


# ── A source on the wrong person ──────────────────────────────────────

def wrong_link(client, fake_structured):
    dana = make(client, "person", "Dana Whitfield")
    org = make(client, "organization", "Harbor Entrepreneurs Network")
    fake_structured.reply = extraction([entity("p1", "Dana Whitfield", role="mentioned", facts=["Received a lifetime award."]),
                                        entity("o1", "Harbor Entrepreneurs Network", kind="organization")],
                                       relationships=[{"source": "p1", "target": "o1", "kind": "works_at", "context": "President"}])
    r = client.post("/api/crm/ingest/notes", json={"text": "Dana Whitfield led Harbor Entrepreneurs Network for years."})
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    if row["status"] == "review":
        assert client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": row["proposal"]}).status_code == 200
        row = client.get(f"/api/crm/ingest/jobs/{row['id']}").json()
    return dana, org, row["result"]["record_id"]


def test_a_source_moves_to_who_it_is_really_about_and_can_be_put_back(client, fake_structured, me):
    dana, org, doc = wrong_link(client, fake_structured)
    preview = client.get(f"/api/crm/entities/{dana['id']}/sources/{doc}").json()
    assert preview["written"] == "Dana Whitfield" and preview["notes"][0]["body"] == "Received a lifetime award."
    assert [x["other"] for x in preview["links"]] == [org["name"]]

    done = client.post(f"/api/crm/entities/{dana['id']}/sources/{doc}/detach", json={"new_name": "Dana W. (Harbor)"}).json()
    other = done["to"]["id"]
    assert [n.body for n in store.notes_of(dana["id"]) if n.evidence_id == doc] == []
    assert [n.body for n in store.notes_of(other) if n.evidence_id == doc] == ["Received a lifetime award."]
    assert not [e for e in store.edges_of(dana["id"]) if doc in (e.source_id, e.target_id) or e.evidence_id == doc]
    assert {e.kind for e in store.edges_of(other)} >= {"works_at"}
    # The next time that full name comes in, it isn't her.
    assert dana["id"] not in {c.entity.id for c in resolve.find_candidates("person", "Dana Whitfield")}

    assert client.post(f"/api/crm/corrections/{done['id']}/undo").status_code == 200
    assert [n.body for n in store.notes_of(dana["id"]) if n.evidence_id == doc] == ["Received a lifetime award."]
    assert store.get_entity(other) is None
    assert dana["id"] in {c.entity.id for c in resolve.find_candidates("person", "Dana Whitfield")}
    assert client.get(f"/api/crm/entities/{dana['id']}/corrections").json() == []


def test_a_surname_the_ai_filled_in_is_not_remembered_as_a_name_they_are_not(client, fake_structured, me):
    jack = make(client, "person", "Jack Marlow")
    row = proposal_row(client, fake_structured, [entity("p1", "Jack Marlow", role="attendee")], text="Jack led the session.")
    p = row["proposal"]
    for e in p["entities"]:
        if e["ref"] == "p1":
            e.update(name="Jack Marlow", action="link", match_id=jack["id"], ambiguous=False)
    client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": p})
    doc = client.get(f"/api/crm/ingest/jobs/{row['id']}").json()["result"]["record_id"]
    assert client.post(f"/api/crm/entities/{jack['id']}/sources/{doc}/detach", json={}).status_code == 200
    assert jack["id"] in {c.entity.id for c in resolve.find_candidates("person", "Jack Marlow")}


def test_a_source_can_just_be_taken_off(client, fake_structured, me):
    dana, _, doc = wrong_link(client, fake_structured)
    done = client.post(f"/api/crm/entities/{dana['id']}/sources/{doc}/detach", json={}).json()
    assert done["to"] is None and done["notes"] == 1
    assert [n for n in store.notes_of(dana["id"]) if n.evidence_id == doc] == []
    assert client.post(f"/api/crm/entities/{dana['id']}/sources/{doc}/detach", json={}).status_code == 422


def test_what_a_source_planted_goes_with_it_and_comes_back(client, fake_structured, me):
    wrong = make(client, "organization", "Harbor Foundation", attributes={"location": "Riverton"}, tags=["energy"])
    store.update_entity(wrong["id"], source="ai")
    fake_structured.reply = extraction([entity("o1", "Harbor Foundation", kind="organization", website="https://ames.example", tags=["vaccines"])])
    r = client.post("/api/crm/ingest/notes", json={"text": "The Harbor Foundation funds vaccines."})
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    if row["status"] == "review":
        client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": row["proposal"]})
        row = client.get(f"/api/crm/ingest/jobs/{row['id']}").json()
    doc = row["result"]["record_id"]
    assert store.get_entity(wrong["id"]).attributes["website"] == "https://ames.example"
    labels = {f["label"]: f["value"] for f in client.get(f"/api/crm/entities/{wrong['id']}/sources/{doc}").json()["fields"]}
    assert labels == {"Website": "https://ames.example", "Tags": "vaccines"}

    done = client.post(f"/api/crm/entities/{wrong['id']}/sources/{doc}/detach", json={"new_name": "Ames Family Foundation"}).json()
    kept, moved = store.get_entity(wrong["id"]), store.get_entity(done["to"]["id"])
    assert "website" not in kept.attributes and kept.attributes["location"] == "Riverton" and kept.tags == ["energy"]
    assert moved.attributes["website"] == "https://ames.example" and moved.tags == ["vaccines"]

    client.post(f"/api/crm/corrections/{done['id']}/undo")
    back = store.get_entity(wrong["id"])
    assert back.attributes["website"] == "https://ames.example" and set(back.tags) == {"energy", "vaccines"}


def test_a_value_another_source_also_gave_stays(client, fake_structured, me):
    p = make(client, "person", "Ana Ruiz")
    store.update_entity(p["id"], source="ai")
    docs = []
    for i, text in enumerate(("Ana Ruiz runs pilots here.", "Ana Ruiz runs pilots there too.")):
        fake_structured.reply = extraction([entity("p1", "Ana Ruiz", title="Pilot lead")], title=f"Doc {i}", doc_type="document")
        r = client.post("/api/crm/ingest/notes", json={"text": text})
        jobs.drain()
        row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
        if row["status"] == "review":
            client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": row["proposal"]})
            row = client.get(f"/api/crm/ingest/jobs/{row['id']}").json()
        docs.append(row["result"]["record_id"])
    client.post(f"/api/crm/entities/{p['id']}/sources/{docs[0]}/detach", json={})
    assert store.get_entity(p["id"]).attributes["title"] == "Pilot lead"
    client.post(f"/api/crm/entities/{p['id']}/sources/{docs[1]}/detach", json={})
    assert "title" not in store.get_entity(p["id"]).attributes


def test_a_title_goes_only_on_the_one_job_it_could_belong_to(client, fake_structured, me):
    fake_structured.reply = extraction(
        [entity("p1", "Ana Ruiz", title="Founder"), entity("o1", "Acme", kind="organization"), entity("o2", "Birch", kind="organization"),
         entity("p2", "Raj Patel", title="Engineer"), entity("o3", "Cedar", kind="organization")],
        relationships=[{"source": "p1", "target": "o1", "kind": "works_at"}, {"source": "p1", "target": "o2", "kind": "works_at"},
                       {"source": "p2", "target": "o3", "kind": "works_at"}])
    r = client.post("/api/crm/ingest/notes", json={"text": "Ana Ruiz works at Acme and Birch. Raj Patel works at Cedar."})
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    if row["status"] == "review":
        client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": row["proposal"]})
    works = [e for e in store.all_edges() if e.kind == "works_at"]
    titles = {store.get_entity(e.target_id).name: e.properties.get("title") for e in works}
    assert titles == {"Acme": None, "Birch": None, "Cedar": "Engineer"}


def test_a_report_about_someone_else_moves_with_everything_it_gave_and_comes_back(client, fake_structured, me):
    sam = make(client, "person", "Sam Reed", attributes={"title": "Mentor"})
    client.post(f"/api/crm/entities/{sam['id']}/notes", json={"body": "Sam's own note."})
    acme = make(client, "organization", "Acme Menus")
    fake_structured.reply = extraction(
        [entity("p1", "Jo Reed", role="subject", title="Founder, Acme Menus", summary="Runs Acme Menus.", facts=["Sold a company in 1999."]), entity("o1", "Acme Menus", kind="organization")],
        doc_type="person_profile", subject_ref="p1",
        relationships=[{"source": "p1", "target": "o1", "kind": "works_at", "context": "Founder"}])
    r = client.post("/api/crm/ingest/notes", json={"text": "A full report about Jo Reed and Acme Menus."})
    jobs.drain()
    row = client.get(f"/api/crm/ingest/jobs/{r.json()['id']}").json()
    assert row["status"] == "review"
    proposal = row["proposal"]
    for e in proposal["entities"]:
        if e["ref"] == "p1":   # as the old matching did: filed it on the wrong person
            e.update(action="link", match_id=sam["id"], ambiguous=False)
    assert client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": proposal}).status_code == 200
    assert {e.kind for e in store.edges_of(sam["id"])} == {"works_at"} and any(n.body == "Sold a company in 1999." for n in store.notes_of(sam["id"]))

    done = client.post(f"/api/crm/entities/{sam['id']}/reports/{row['id']}/move", json={"new_name": "Jo Reed"}).json()
    jo = done["to"]["id"]
    assert [n.body for n in store.notes_of(sam["id"])] == ["Sam's own note."]
    assert store.edges_of(sam["id"]) == [] and {store.get_entity(e.target_id).name for e in store.edges_of(jo)} == {"Acme Menus"}
    assert sorted(n.body for n in store.notes_of(jo))[0].startswith("A full report") or any("full report" in n.body for n in store.notes_of(jo))
    assert store.get_entity(sam["id"]).attributes["title"] == "Mentor" and store.get_entity(jo).summary == "Runs Acme Menus."
    assert client.get(f"/api/crm/people/{sam['id']}/research").json()["reports"] == []
    assert client.get(f"/api/crm/people/{jo}/research").json()["reports"][0]["about_them"]

    assert client.post(f"/api/crm/corrections/{done['id']}/undo").status_code == 200
    assert any(n.body == "Sold a company in 1999." for n in store.notes_of(sam["id"])) and store.get_entity(jo) is None
    assert client.get(f"/api/crm/people/{sam['id']}/research").json()["reports"][0]["about_them"]


def test_guessed_links_come_up_for_a_look_until_you_settle_them(client, fake_structured, me):
    whitfield = make(client, "person", "Dana Whitfield")
    row = proposal_row(client, fake_structured, [entity("p1", "Dana Whitfield", role="attendee")])
    p = row["proposal"]
    for e in p["entities"]:
        if e["ref"] == "p1":   # as the old matching did: linked her without asking, under the name it was shown
            e.update(name="Dana Whitfield", action="link", match_id=whitfield["id"], ambiguous=False)
    assert client.post(f"/api/crm/ingest/jobs/{row['id']}/apply", json={"proposal": p}).status_code == 200
    doc = client.get(f"/api/crm/ingest/jobs/{row['id']}").json()["result"]["record_id"]
    items = client.get("/api/crm/link-checks").json()["items"]
    assert [(i["entity"]["id"], i["evidence"]["id"]) for i in items] == [(whitfield["id"], doc)]
    assert "only says “Dana”" in items[0]["why"]
    client.post("/api/crm/link-checks/right", json={"entity_id": whitfield["id"], "evidence_id": doc})
    assert client.get("/api/crm/link-checks").json()["total"] == 0


def test_a_corrected_name_reaches_the_summaries_but_not_the_original_text(client, fake_structured, me):
    dana = make(client, "person", "Dana Porter")
    meeting = make(client, "meeting", "Chairs", summary="Dana Whitfield gave the update.", attributes={"key_points": ["Dana Whitfield spoke"]})
    link(client, dana, "attended", meeting)
    store.add_note(meeting["id"], "Dana Whitfield raw text", source="trailmix", evidence_id=meeting["id"])
    assert client.post(f"/api/crm/entities/{dana['id']}/rename-text", json={"old": "Dana Whitfield", "new": "Dana Porter"}).json()["changed"] == 1
    m = store.get_entity(meeting["id"])
    assert m.summary == "Dana Porter gave the update." and m.attributes["key_points"] == ["Dana Porter spoke"]
    assert store.notes_of(meeting["id"])[0].body == "Dana Whitfield raw text"


# ── Words about someone ───────────────────────────────────────────────

def test_an_overview_you_wrote_stays_yours_until_you_ask_for_another(client, me):
    p = make(client, "person", "Ana Ruiz", summary="Runs pilots.")
    state = client.put(f"/api/crm/people/{p['id']}/overview", json={"body": "My own words."}).json()
    assert state["overview"]["body"] == "My own words." and state["overview"]["mine"] and state["overview"]["current"]
    jobs.enqueue("crm", "overview_now", p["id"])
    jobs.drain()
    assert client.get(f"/api/crm/people/{p['id']}/overview").json()["overview"]["body"] == "My own words."
    assert not client.post(f"/api/crm/people/{p['id']}/overview").json()["overview"]["mine"]


def test_a_note_can_be_reworded(client):
    p = make(client, "person", "Ana Ruiz")
    note = client.post(f"/api/crm/entities/{p['id']}/notes", json={"body": "Wrong."}).json()
    assert client.patch(f"/api/crm/notes/{note['id']}", json={"body": "Right."}).json()["body"] == "Right."


# ── Hats ──────────────────────────────────────────────────────────────

def people(client, **params):
    return {r["person"]["name"] for r in client.get("/api/crm/people", params={"limit": 100, **params}).json()["items"]}


def test_a_hat_is_a_lens_on_one_book(client, me):
    parks, cold = hats.create("Parks Board"), hats.create("Frostline")
    chad, eli, both = make(client, "person", "Theo"), make(client, "person", "Eli"), make(client, "person", "Both")
    nobody = make(client, "person", "Nobody")
    city = make(client, "organization", "City of Alderton")
    link(client, chad, "works_at", city)
    meeting = make(client, "meeting", "Parks meeting")
    link(client, chad, "attended", meeting)
    link(client, both, "attended", meeting)
    hats.stamp(meeting["id"], parks)
    hats.place(cold, [eli["id"], both["id"]], "you")

    assert people(client, hat=parks) == {"Theo", "Both"}
    assert people(client, hat=cold) == {"Eli", "Both"}
    assert people(client, hat="none") == {"Nobody"}
    assert nobody["name"] in people(client) and nobody["name"] in people(client, hat="all")
    orgs = client.get("/api/crm/organizations", params={"hat": parks, "scope": "all"}).json()["items"]
    assert [o["org"]["name"] for o in orgs] == ["City of Alderton"]
    assert client.get("/api/crm/entities", params={"kind": "meeting", "hat": cold}).json()["total"] == 0

    # Wearing one: "active" follows it, and a new person belongs to it.
    client.put("/api/crm/hats/active", json={"id": parks})
    assert people(client, hat="active") == {"Theo", "Both"}
    make(client, "person", "New Hire")
    assert "New Hire" in people(client, hat="active")

    # Taking someone out holds, whatever they're linked to.
    client.post(f"/api/crm/hats/{parks}/place", json={"ids": [both["id"]], "how": "no"})
    assert "Both" not in people(client, hat=parks)
    client.post(f"/api/crm/hats/{parks}/place", json={"ids": [both["id"]], "how": None})
    assert "Both" in people(client, hat=parks)

    # The hat can go; nobody goes with it.
    client.delete(f"/api/crm/hats/{parks}")
    assert client.get("/api/crm/hats").json()["active"] is None
    assert "Theo" in people(client)


def test_people_can_be_narrowed_by_each_kind_of_group_on_its_own(client, me):
    a = make(client, "person", "Ann", tags=["investor"])
    b = make(client, "person", "Bea", tags=["investor", "mentor"])
    c = make(client, "person", "Cy", tags=["mentor"])
    acme = make(client, "organization", "Acme")
    link(client, a, "works_at", acme)
    link(client, b, "works_at", acme)
    meeting = make(client, "meeting", "Tagged", tags=["cold-chain"])
    link(client, c, "attended", meeting)
    assert people(client, tag="investor") == {"Ann", "Bea"}
    assert people(client, org=acme["id"], tag="mentor") == {"Bea"}
    assert people(client, mtag="cold-chain") == {"Cy"}
    f = client.get("/api/crm/people/facets").json()
    assert {t["name"]: t["count"] for t in f["tags"]} == {"investor": 2, "mentor": 2}
    assert [(o["name"], o["count"]) for o in f["orgs"]] == [("Acme", 2)]
    assert [(t["name"], t["count"]) for t in f["meeting_tags"]] == [("cold-chain", 1)]
    narrowed = client.get("/api/crm/people/facets", params={"org": acme["id"]}).json()
    assert {t["name"]: t["count"] for t in narrowed["tags"]} == {"investor": 2, "mentor": 1}
