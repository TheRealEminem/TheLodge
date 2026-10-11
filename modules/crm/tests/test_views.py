from modules.crm.server import views
from crm_helpers import link, make


def test_list_is_enriched(client):
    ana = make(client, "person", "Ana Diaz", attributes={"title": "CTO"})
    acme = make(client, "organization", "Acme Corp")
    link(client, ana, "works_at", acme)
    item = client.get("/api/crm/entities", params={"kind": "person"}).json()["items"][0]
    assert item["subtitle"] == "CTO · Acme Corp" and item["degree"] == 1
    by_degree = client.get("/api/crm/entities", params={"sort": "connections"}).json()["items"]
    assert {e["name"] for e in by_degree[:2]} == {"Ana Diaz", "Acme Corp"}


def test_detail_timeline_and_notes(client):
    ana = make(client, "person", "Ana")
    meeting = make(client, "meeting", "Kickoff", occurred_at="2026-03-01T15:00:00Z")
    link(client, ana, "attended", meeting)
    assert client.post(f"/api/crm/entities/{ana['id']}/notes", json={"body": "Prefers mornings\nand email"}).status_code == 201

    events = client.get(f"/api/crm/entities/{ana['id']}/timeline").json()
    assert [e["type"] for e in events] == ["note", "meeting"]
    assert next(e for e in events if e["type"] == "note")["title"] == "Prefers mornings"
    detail = client.get(f"/api/crm/entities/{ana['id']}").json()
    assert detail["entity"]["last_interaction_at"].startswith("2026-03-01")
    assert client.get("/api/crm/entities/nope/timeline").status_code == 404


def test_relationship_view_labels(client):
    ana, acme = make(client, "person", "Ana"), make(client, "organization", "Acme")
    link(client, ana, "works_at", acme)
    [view] = client.get(f"/api/crm/entities/{acme['id']}").json()["relationships"]
    assert (view["label"], view["direction"], view["other"]["name"]) == ("employs", "in", "Ana")


def test_org_timeline_shows_team_meetings(client):
    ana, acme = make(client, "person", "Ana"), make(client, "organization", "Acme")
    m = make(client, "meeting", "Pilot sync", occurred_at="2026-05-04T10:00:00Z")
    link(client, ana, "works_at", acme)
    link(client, ana, "attended", m)
    [ev] = client.get(f"/api/crm/entities/{acme['id']}/timeline").json()
    assert ev["title"] == "Pilot sync" and ev["detail"] == "with Ana" and ev["via"]["name"] == "Ana"


def test_demo_seed_dashboard_and_intro_path(client):
    r = client.post("/api/crm/admin/demo")
    assert r.status_code == 200, r.text
    assert client.post("/api/crm/admin/demo").status_code == 409

    dash = client.get("/api/crm/dashboard").json()
    assert dash["me"]["name"] == "Jordan Reyes"
    assert dash["counts"]["person"] == 31
    assert len(dash["weekly_activity"]) == 26
    assert sum(dash["tiers"].values()) == 30
    assert dash["strong"] and all(r["connection"]["tier"] == "strong" for r in dash["strong"])
    assert all(r["connection"]["tier"] in ("strong", "working") for r in dash["reconnect"])

    elena = client.get("/api/crm/entities", params={"q": "Elena Petrova"}).json()["items"][0]
    paths = client.get("/api/crm/graph/paths", params={"target": elena["id"], "through": "person"}).json()["paths"]
    assert [n["name"] for n in paths[0]["nodes"]] == ["Jordan Reyes", "Hannah Cole", "Elena Petrova"]

    assert client.delete("/api/crm/admin/demo").json()["deleted"] > 50
    assert client.get("/api/crm/dashboard").json()["me"] is None


def test_views_follow_writes_and_can_be_seen_from_another_person(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana, ben = make(client, "person", "Ana"), make(client, "person", "Ben")
    link(client, me, "knows", ana, strength=5)
    assert views.get().tier(ana["id"]) == "strong"
    link(client, ben, "knows", ana, strength=2)
    # A write moved the cache: Ana now has a mutual contact for Ben's view.
    assert views.get(ben["id"]).tier(ana["id"]) == "light"
    assert views.get().tier(ben["id"]) == "indirect"
    client.delete(f"/api/crm/entities/{ana['id']}")
    assert ana["id"] not in views.get().conns


def test_dashboard_without_data(client):
    dash = client.get("/api/crm/dashboard").json()
    assert dash["me"] is None and dash["counts"] == {} and dash["strong"] == []
