from crm_helpers import link, make


def _network(client):
    me = (client.put("/api/crm/me", json={"name": "Me"})).json()
    a = make(client, "person", "Alice")
    b = make(client, "person", "Bob")
    c = make(client, "person", "Carol")
    target = make(client, "person", "Target")
    org = make(client, "organization", "BigCo")
    link(client, me, "knows", a, strength=2)
    link(client, a, "knows", target, strength=2)
    link(client, me, "knows", b, strength=5)
    link(client, b, "knows", target, strength=5)
    # A shorter-looking route through an organization, and a longer route via Carol.
    link(client, me, "works_at", org)
    link(client, target, "works_at", org)
    link(client, me, "knows", c)
    link(client, c, "knows", a)
    return me, a, b, c, target, org


def test_shortest_paths_strongest_first(client):
    me, a, b, c, target, org = _network(client)

    r = client.get("/api/crm/graph/paths", params={"target": target["id"]})
    assert r.status_code == 200, r.text
    paths = r.json()["paths"]
    assert {p["hops"] for p in paths} == {2}
    names = [[n["name"] for n in p["nodes"]] for p in paths]
    assert names[0] == ["Me", "Bob", "Target"]
    assert ["Me", "BigCo", "Target"] in names
    assert paths[0]["score"] == 1.0

    r = client.get("/api/crm/graph/paths", params={"target": target["id"], "through": "person"})
    names = [[n["name"] for n in p["nodes"]] for p in r.json()["paths"]]
    assert ["Me", "BigCo", "Target"] not in names
    assert names[0] == ["Me", "Bob", "Target"]


def test_no_path(client):
    me = (client.put("/api/crm/me", json={"name": "Me"})).json()
    loner = make(client, "person", "Loner")
    r = client.get("/api/crm/graph/paths", params={"target": loner["id"], "source": me["id"]})
    assert r.json()["paths"] == []


def test_ego_and_overview(client):
    me, a, b, c, target, org = _network(client)

    g = (client.get("/api/crm/graph", params={"center": me["id"], "depth": 1})).json()
    names = {n["name"] for n in g["nodes"]}
    assert names == {"Me", "Alice", "Bob", "Carol", "BigCo"}
    depths = {n["name"]: n["depth"] for n in g["nodes"]}
    assert depths["Me"] == 0 and depths["Bob"] == 1
    # Links among included nodes only (Carol-Alice is inside, Alice-Target is not).
    assert len(g["links"]) == 5

    g = (client.get("/api/crm/graph", params={"kinds": "person"})).json()
    assert {n["kind"] for n in g["nodes"]} == {"person"}
    assert not g["truncated"]

    g = (client.get("/api/crm/graph", params={"max_nodes": 10})).json()
    assert len(g["nodes"]) == 6

    g = (client.get("/api/crm/graph", params={"center": me["id"], "depth": 2, "max_nodes": 10})).json()
    assert "Target" in {n["name"] for n in g["nodes"]}
