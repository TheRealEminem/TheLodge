from core.server import db
from modules.crm.server import resolve, store

from crm_helpers import link, make


def test_create_list_search(client):
    ana = make(client, "person", "Ana Diaz", attributes={"title": "CTO", "email": "ana@x.com"}, tags=["Investor", " investor "])
    acme = make(client, "organization", "Acme Corp")
    link(client, ana, "works_at", acme)
    assert ana["tags"] == ["investor"]

    body = client.get("/api/crm/entities", params={"kind": "person"}).json()
    assert body["total"] == 1 and body["items"][0]["name"] == "Ana Diaz"
    assert [e["name"] for e in client.get("/api/crm/entities", params={"q": "acme"}).json()["items"]] == ["Acme Corp"]
    assert client.get("/api/crm/entities", params={"q": "100%_"}).json()["total"] == 0
    assert client.get("/api/crm/entities", params={"tag": "investor"}).json()["total"] == 1

    groups = client.get("/api/search", params={"q": "Ana"}).json()
    assert any(h["id"] == ana["id"] for g in groups if g["module"] == "crm" for h in g["hits"])
    assert [h["id"] for g in client.get("/api/search", params={"q": "cto"}).json() for h in g["hits"]] == [ana["id"]]


def test_update_reindexes_and_delete_cascades(client):
    ana = make(client, "person", "Ana")
    acme = make(client, "organization", "Acme")
    link(client, ana, "works_at", acme)
    r = client.patch(f"/api/crm/entities/{ana['id']}", json={"name": "Anabel", "tags": ["VC Partner"]})
    assert r.json()["name"] == "Anabel" and r.json()["tags"] == ["vc-partner"]
    assert [h["id"] for g in client.get("/api/search", params={"q": "Anab"}).json() for h in g["hits"]] == [ana["id"]]

    assert client.delete(f"/api/crm/entities/{acme['id']}").status_code == 204
    assert db.one("SELECT count(*) AS n FROM crm_relationships")["n"] == 0
    assert client.get(f"/api/crm/entities/{acme['id']}").status_code == 404
    assert client.delete(f"/api/crm/entities/{acme['id']}").status_code == 404


def test_rejects_unknown_kind(client):
    assert client.post("/api/crm/entities", json={"kind": "spaceship", "name": "X"}).status_code == 422


def test_relationship_rules(client):
    ana, ben = make(client, "person", "Ana"), make(client, "person", "Ben")
    acme = make(client, "organization", "Acme")

    def post(s, t, kind):
        return client.post("/api/crm/relationships", json={"source_id": s["id"], "target_id": t["id"], "kind": kind})

    assert post(ana, ben, "works_at").status_code == 422
    link(client, ana, "knows", ben)
    assert post(ben, ana, "knows").status_code == 409  # symmetric kinds dedupe both ways
    assert post(ana, ana, "knows").status_code == 422

    edge = link(client, ana, "works_at", acme, properties={"title": "CEO"})
    r = client.patch(f"/api/crm/relationships/{edge['id']}", json={"strength": 5, "ended_at": "2025-01-31"})
    assert r.json()["strength"] == 5 and r.json()["ended_at"] == "2025-01-31"
    assert client.delete(f"/api/crm/relationships/{edge['id']}").status_code == 204
    assert client.patch(f"/api/crm/relationships/{edge['id']}", json={"strength": 2}).status_code == 404


def test_rating_your_own_tie_marks_it_user_set(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana = make(client, "person", "Ana")
    edge = link(client, me, "knows", ana)
    r = client.patch(f"/api/crm/relationships/{edge['id']}", json={"strength": 5}).json()
    assert r["properties"]["user_set"] is True


def test_notes(client):
    ana = make(client, "person", "Ana")
    n = client.post(f"/api/crm/entities/{ana['id']}/notes", json={"body": "Prefers mornings"})
    assert n.status_code == 201
    assert [x["body"] for x in client.get(f"/api/crm/entities/{ana['id']}/notes").json()] == ["Prefers mornings"]
    assert client.delete(f"/api/crm/notes/{n.json()['id']}").status_code == 204


def test_merge(client):
    daniel = make(client, "person", "Daniel Smith", attributes={"email": "d@x.com"})
    dan = make(client, "person", "Dan Smith", attributes={"title": "Partner"}, tags=["vc"])
    acme = make(client, "organization", "Acme")
    ana = make(client, "person", "Ana")
    link(client, dan, "works_at", acme)
    link(client, daniel, "knows", ana, strength=2)
    link(client, ana, "knows", dan, strength=5)  # duplicate once merged
    link(client, dan, "knows", daniel)  # becomes a self-loop; dropped
    client.post(f"/api/crm/entities/{dan['id']}/notes", json={"body": "met at demo day"})

    r = client.post(f"/api/crm/entities/{dan['id']}/merge", json={"into_id": daniel["id"]})
    assert r.status_code == 200, r.text
    merged = r.json()
    assert merged["attributes"]["email"] == "d@x.com" and merged["attributes"]["title"] == "Partner"
    assert merged["attributes"]["aliases"] == ["Dan Smith"] and merged["tags"] == ["vc"]
    assert client.get(f"/api/crm/entities/{dan['id']}").status_code == 404
    edges = store.edges_of(daniel["id"])
    assert sorted(e.kind for e in edges) == ["knows", "works_at"]
    assert next(e for e in edges if e.kind == "knows").strength == 5
    assert [n.body for n in store.notes_of(daniel["id"])] == ["met at demo day"]

    assert client.post(f"/api/crm/entities/{ana['id']}/merge", json={"into_id": acme["id"]}).status_code == 422
    assert client.post(f"/api/crm/entities/{ana['id']}/merge", json={"into_id": ana["id"]}).status_code == 422


def test_me(client):
    assert client.get("/api/crm/me").json() is None
    me = client.put("/api/crm/me", json={"name": "Jordan"}).json()
    assert me["is_self"] is True
    other = make(client, "person", "Alex")
    assert client.put("/api/crm/me", json={"entity_id": other["id"]}).json()["id"] == other["id"]
    assert client.get(f"/api/crm/entities/{me['id']}").json()["entity"]["is_self"] is False
    assert client.put("/api/crm/me", json={}).status_code == 422


def test_merging_me_keeps_me(client):
    me = client.put("/api/crm/me", json={"name": "Sam"}).json()
    dup = make(client, "person", "Sam M")
    client.post(f"/api/crm/entities/{me['id']}/merge", json={"into_id": dup["id"]})
    assert store.get_me().id == dup["id"]


def test_upsert_edge_keeps_curated_values(client):
    ana, acme = make(client, "person", "Ana"), make(client, "organization", "Acme")
    first, created = store.upsert_edge(ana["id"], acme["id"], "works_at", properties={"title": "CTO"}, started_at="2020-01-01")
    assert created
    again, created = store.upsert_edge(ana["id"], acme["id"], "works_at", properties={"title": "Intern", "context": "x"},
                                       started_at="2019-01-01", ended_at="2024-01-01")
    assert not created and again.id == first.id
    assert again.properties == {"title": "CTO", "context": "x"}
    assert str(again.started_at) == "2020-01-01" and str(again.ended_at) == "2024-01-01"


def test_org_matching_ignores_generic_words(client):
    for name in ("Oak Foundation", "PGX Foundation", "Nora Linden Consulting", "Juno Innovation Hub", "Kellan Trust USA"):
        make(client, "organization", name)
    assert resolve.find_candidates("organization", "Bill & Melinda Gates Foundation") == []
    assert resolve.find_candidates("organization", "Harbor Consulting") == []
    assert resolve.find_candidates("organization", "Innovation Marlow") == []
    [Kellan] = resolve.find_candidates("organization", "Contact 241")
    assert Kellan.entity.name == "Kellan Trust USA"


def test_email_alias_and_exact_matches_are_strong(client):
    make(client, "person", "Daniel Smith", attributes={"email": "D@X.com", "aliases": ["Danny"]})
    assert resolve.find_candidates("person", "Someone Else", "d@x.com")[0].reason == "email"
    top, ambiguous = resolve.pick_match(resolve.find_candidates("person", "danny"), 0.6)
    assert top.reason == "alias" and not ambiguous
    top, ambiguous = resolve.pick_match(resolve.find_candidates("person", "daniel smith"), 0.6)
    assert top.reason == "exact name"


def test_similar_names_and_ambiguity(client):
    make(client, "person", "Sarah Chen")
    make(client, "person", "Sarah Cohen")
    cands = resolve.find_candidates("person", "Sarah")
    match, ambiguous = resolve.pick_match(cands, 0.6)
    assert match is None and ambiguous
    # A typo of one record is a clear match.
    match, ambiguous = resolve.pick_match(resolve.find_candidates("person", "Sara Chen"), 0.6)
    assert match.entity.name == "Sarah Chen" and not ambiguous
    # Kinds don't mix.
    assert resolve.find_candidates("organization", "Sarah Chen") == []


def test_index_follows_writes(client):
    assert resolve.find_candidates("person", "Priya Nair") == []
    make(client, "person", "Priya Nair")
    assert resolve.find_candidates("person", "Priya Nair")[0].reason == "exact name"
