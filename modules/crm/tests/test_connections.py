from crm_helpers import link, make


def _world(client):
    """Me at Acme; a close friend, a colleague, someone met once, someone who
    only came up in a meeting, a friend-of-a-friend, and a stranger."""
    me = (client.put("/api/crm/me", json={"name": "Me"})).json()
    acme = make(client, "organization", "Acme")
    other_co = make(client, "organization", "Globex")
    nowhere = make(client, "organization", "Initech")
    friend = make(client, "person", "Fran Friend")
    colleague = make(client, "person", "Cole League")
    met = make(client, "person", "Mette Once")
    heard = make(client, "person", "Hugo Heard")
    fof = make(client, "person", "Fofi Far")
    stranger = make(client, "person", "Stan Stranger")
    call = make(client, "meeting", "Coffee with Mette", occurred_at="2026-09-01T16:00:00Z")

    link(client, me, "works_at", acme)
    link(client, colleague, "works_at", acme)
    link(client, me, "knows", friend, strength=5)
    link(client, friend, "knows", fof, strength=3)
    link(client, fof, "works_at", other_co)
    link(client, me, "attended", call)
    link(client, met, "attended", call)
    link(client, heard, "discussed_in", call)
    link(client, nowhere, "discussed_in", call)
    return locals()


def test_tiers_from_the_graph(client):
    w = _world(client)
    page = (client.get("/api/crm/people")).json()
    tiers = {r["person"]["name"]: r["connection"]["tier"] for r in page["items"]}
    assert tiers == {
        "Fran Friend": "strong",
        "Cole League": "working",
        "Mette Once": "light",
        "Hugo Heard": "indirect",
        "Fofi Far": "indirect",
        "Stan Stranger": "none",
    }
    # Me is the center, not a row; strongest first.
    assert [r["person"]["name"] for r in page["items"]][0] == "Fran Friend"
    assert page["tiers"] == {"strong": 1, "working": 1, "light": 1, "indirect": 2, "none": 1}

    rows = {r["person"]["name"]: r for r in page["items"]}
    assert rows["Cole League"]["connection"]["roles"] == ["colleague at Acme"]
    assert rows["Cole League"]["org"]["name"] == "Acme"
    assert rows["Mette Once"]["connection"]["meetings"] == 1
    # Hugo came up in a meeting where Mette was present: Mette is the link.
    assert [v["name"] for v in rows["Hugo Heard"]["connection"]["via"]] == ["Mette Once"]
    assert [m["name"] for m in rows["Fofi Far"]["connection"]["mutual"]] == ["Fran Friend"]

    only = (client.get("/api/crm/people", params={"tier": "indirect", "sort": "name"})).json()
    assert [r["person"]["name"] for r in only["items"]] == ["Fofi Far", "Hugo Heard"]
    at_acme = (client.get("/api/crm/people", params={"org": w["acme"]["id"]})).json()
    assert [r["person"]["name"] for r in at_acme["items"]] == ["Cole League"]


def test_rating_overrides_and_resets(client):
    w = _world(client)
    pid = w["stranger"]["id"]

    c = (client.put(f"/api/crm/people/{pid}/connection", json={"strength": 4})).json()
    assert c["tier"] == "strong" and c["user_set"] and c["strength"] == 4

    c = (client.put(f"/api/crm/people/{pid}/connection", json={"strength": None})).json()
    assert c["tier"] == "none" and not c["user_set"]
    # The tie created by the rating is gone again.
    detail = (client.get(f"/api/crm/entities/{pid}")).json()
    assert detail["relationships"] == []

    # Rating an existing tie keeps the tie when the rating is cleared.
    fid = w["friend"]["id"]
    c = (client.put(f"/api/crm/people/{fid}/connection", json={"strength": 2})).json()
    assert c["tier"] == "light" and c["user_set"]
    c = (client.put(f"/api/crm/people/{fid}/connection", json={"strength": None})).json()
    assert c["tier"] == "light" and not c["user_set"] and c["strength"] == 2


def test_organizations_scoped_by_who_you_know(client):
    _world(client)
    page = (client.get("/api/crm/organizations")).json()
    assert page["scopes"] == {"known": 1, "connected": 2, "mentioned": 1, "all": 3}
    assert [r["org"]["name"] for r in page["items"]] == ["Acme"]
    acme = page["items"][0]
    assert acme["mine"] == "current" and acme["known"] == 1 and acme["best_tier"] == "working"

    mentioned = (client.get("/api/crm/organizations", params={"scope": "mentioned"})).json()
    assert [r["org"]["name"] for r in mentioned["items"]] == ["Initech"]
    assert mentioned["items"][0]["mentions"] == 1


def test_profile_context(client):
    w = _world(client)
    ctx = (client.get(f"/api/crm/entities/{w['met']['id']}/context")).json()
    assert ctx["connection"]["tier"] == "light"
    [meeting] = ctx["meetings"]
    assert meeting["event"]["name"] == "Coffee with Mette" and meeting["role"] == "attended" and meeting["with_me"]
    assert [p["name"] for p in meeting["people"]] == ["Me"]

    ctx = (client.get(f"/api/crm/entities/{w['fof']['id']}/context")).json()
    assert [(a["org"]["name"], a["current"]) for a in ctx["affiliations"]] == [("Globex", True)]
    assert [(p["person"]["name"], p["relation"], p["tier"]) for p in ctx["people"]] == [("Fran Friend", "knows", "strong")]

    ctx = (client.get(f"/api/crm/entities/{w['acme']['id']}/context")).json()
    assert ctx["org"]["mine"] == "current"
    assert [(p["person"]["name"], p["relation"]) for p in ctx["people"]] == [("Cole League", "works at")]

    ctx = (client.get(f"/api/crm/entities/{w['call']['id']}/context")).json()
    assert [(p["person"]["name"], p["relation"]) for p in ctx["people"]] == [
        ("Me", "attended"),
        ("Mette Once", "attended"),
        ("Hugo Heard", "discussed"),
    ]
    assert [o["org"]["name"] for o in ctx["orgs"]] == ["Initech"]


def test_big_events_count_less_than_one_to_ones(client):
    me = (client.put("/api/crm/me", json={"name": "Me"})).json()
    crowd = [make(client, "person", f"Guest {i}") for i in range(20)]
    one = make(client, "person", "One On One")
    expo = make(client, "meeting", "Expo", occurred_at="2026-09-01T16:00:00Z")
    coffee = make(client, "meeting", "Coffee", occurred_at="2026-09-01T16:00:00Z")
    for p in (me, *crowd):
        link(client, p, "attended", expo)
    for p in (me, one):
        link(client, p, "attended", coffee)
    rows = {r["person"]["name"]: r["connection"] for r in (client.get("/api/crm/people")).json()["items"]}
    assert rows["One On One"]["score"] > rows["Guest 0"]["score"]
    assert rows["Guest 0"]["tier"] == "light"
