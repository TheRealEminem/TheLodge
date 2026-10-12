"""The people-first network: lines between people with reasons, and groups (organizations, topics, tags)."""
from crm_helpers import link, make

from modules.crm.server import people_net


def people(client, *names):
    return [make(client, "person", n) for n in names]


def net_json(client, **params):
    r = client.get("/api/crm/network", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def line(data, a, b):
    ids = {a["id"], b["id"]}
    found = [lk for lk in data["links"] if {lk["source"], lk["target"]} == ids]
    return found[0] if found else None


def test_only_people_are_nodes_and_a_direct_line_says_how_well(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana, ben = people(client, "Ana", "Ben")
    make(client, "organization", "Acme")
    link(client, ana, "knows", ben, strength=4)
    link(client, me, "knows", ana, strength=5)
    data = net_json(client)
    assert {n["name"] for n in data["nodes"]} == {"Me", "Ana", "Ben"}
    direct = line(data, ana, ben)
    assert direct["basis"] == "direct" and direct["weight"] == 4 and direct["why"][0]["text"] == "Know each other"
    assert line(data, me, ana)["why"][0]["text"] == "You know them"


def test_two_people_who_took_part_in_the_same_meeting_are_connected_and_the_meeting_is_the_reason(client):
    ana, ben, cy = people(client, "Ana", "Ben", "Cy")
    meeting = make(client, "meeting", "Kickoff")
    for p in (ana, ben):
        link(client, p, "attended", meeting)
    link(client, cy, "discussed_in", meeting)  # came up, didn't take part
    data = net_json(client)
    met = line(data, ana, ben)
    assert met["basis"] == "met" and met["why"][0] == {"text": "Both took part in Kickoff",
                                                      "ref": {"id": meeting["id"], "kind": "meeting", "name": "Kickoff"}}
    assert line(data, ana, cy)["basis"] == "mentioned" and "Cy came up in Kickoff" in line(data, ana, cy)["why"][0]["text"]
    assert line(data, ben, cy)["basis"] == "mentioned"


def test_a_crowded_event_says_nothing_about_who_knows_whom(client):
    crowd = people(client, *[f"P{i}" for i in range(people_net.MAX_PARTICIPANTS + 1)])
    summit = make(client, "meeting", "Summit")
    for p in crowd:
        link(client, p, "attended", summit)
    assert net_json(client)["links"] == []


def test_the_same_employer_makes_a_group_not_a_line(client):
    ana, ben, cy = people(client, "Ana", "Ben", "Cy")
    acme, other = make(client, "organization", "Acme"), make(client, "organization", "Lonely Inc")
    link(client, ana, "works_at", acme)
    link(client, ben, "advises", acme)
    link(client, cy, "works_at", other)
    link(client, cy, "works_at", acme, ended_at="2020-01-01")  # formerly: not a member
    data = net_json(client)
    assert data["links"] == []
    groups = {g["name"]: g for g in data["groups"]}
    assert groups["Acme"]["size"] == 2 and groups["Acme"]["kind"] == "organization" and "Lonely Inc" not in groups
    detail = client.get(f"/api/crm/network/groups/org:{acme['id']}").json()
    assert {m["name"]: m["why"] for m in detail["members"]} == {"Ana": "Works there", "Ben": "Advises them"}


def test_someone_in_two_groups_is_one_node_listing_both(client):
    ana, ben, cy = people(client, "Ana", "Ben", "Cy")
    acme = make(client, "organization", "Acme")
    for p in (ana, ben):
        link(client, p, "works_at", acme)
    for p in (ana, cy):
        client.patch(f"/api/crm/entities/{p['id']}", json={"tags": ["Mentor"]})
    data = net_json(client)
    assert len([n for n in data["nodes"] if n["name"] == "Ana"]) == 1
    ana_node = next(n for n in data["nodes"] if n["name"] == "Ana")
    assert set(ana_node["groups"]) == {f"org:{acme['id']}", "tag:mentor"}
    assert next(n for n in data["nodes"] if n["name"] == "Ben")["groups"] == [f"org:{acme['id']}"]
    assert next(n for n in data["nodes"] if n["name"] == "Ana")["subtitle"].endswith("Acme")


def test_a_group_of_one_is_not_a_group_and_you_are_never_in_one(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana, = people(client, "Ana")
    acme = make(client, "organization", "Acme")
    link(client, me, "works_at", acme)
    link(client, ana, "works_at", acme)
    client.patch(f"/api/crm/entities/{ana['id']}", json={"tags": ["solo"]})
    assert net_json(client)["groups"] == []


def test_a_topic_includes_people_who_took_part_or_came_up_more_than_once(client):
    ana, ben, cy, dee = people(client, "Ana", "Ben", "Cy", "Dee")
    topic = make(client, "topic", "Cold chain")
    m1, m2 = make(client, "meeting", "Call 1"), make(client, "meeting", "Call 2")
    for m in (m1, m2):
        link(client, topic, "discussed_in", m)
    link(client, ana, "attended", m1)           # took part: counts for 2
    link(client, ben, "discussed_in", m1)       # came up once: 1, not enough
    link(client, cy, "discussed_in", m1)
    link(client, cy, "discussed_in", m2)        # came up twice: enough
    link(client, dee, "related_to", topic)      # linked by hand
    detail = client.get(f"/api/crm/network/groups/topic:{topic['id']}").json()
    assert {m["name"] for m in detail["members"]} == {"Ana", "Cy", "Dee"}
    assert {m["name"]: m["why"] for m in detail["members"]}["Ana"] == "Took part in Call 1"


def test_focusing_on_a_person_keeps_their_neighborhood_only(client):
    a, b, c, d = people(client, "A", "B", "C", "D")
    link(client, a, "knows", b)
    link(client, b, "knows", c)
    link(client, c, "knows", d)
    one = net_json(client, focus=a["id"], depth=1)
    assert {n["name"] for n in one["nodes"]} == {"A", "B"}
    two = net_json(client, focus=a["id"], depth=2)
    assert {n["name"]: n["depth"] for n in two["nodes"]} == {"A": 0, "B": 1, "C": 2}
    assert client.get("/api/crm/network", params={"focus": "nope"}).status_code == 404


def test_the_evidence_for_a_person_is_the_meetings_and_documents_with_who_else_was_there(client):
    ana, ben, cy = people(client, "Ana", "Ben", "Cy")
    meeting, doc = make(client, "meeting", "Kickoff"), make(client, "document", "Notes")
    link(client, ana, "attended", meeting)
    link(client, ben, "attended", meeting)
    link(client, cy, "mentioned_in", doc)
    link(client, ana, "authored", doc)
    ev = client.get(f"/api/crm/network/evidence/{ana['id']}").json()
    by_name = {e["name"]: e for e in ev}
    assert set(by_name) == {"Kickoff", "Notes"}
    assert by_name["Kickoff"]["role"] == "took part" and by_name["Kickoff"]["people"] == [ben["id"]]
    assert by_name["Notes"]["kind"] == "document" and by_name["Notes"]["people"] == [cy["id"]]
    assert client.get("/api/crm/network/evidence/nope").status_code == 404


def test_paths_run_through_people_and_each_hop_says_why(client):
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana, target = people(client, "Ana", "Target")
    meeting = make(client, "meeting", "Demo day")
    link(client, me, "knows", ana, strength=5)
    link(client, ana, "attended", meeting)
    link(client, target, "attended", meeting)
    link(client, me, "attended", meeting)  # also puts me with Target
    out = client.get("/api/crm/network/paths", params={"target": target["id"]}).json()
    assert out["target"]["name"] == "Target" and out["paths"][0]["hops"] == 1
    assert out["paths"][0]["links"][0]["label"] == "Both took part in Demo day"
    far = people(client, "Far")[0]
    link(client, target, "knows", far, strength=3)
    out = client.get("/api/crm/network/paths", params={"target": far["id"]}).json()
    assert [n["name"] for n in out["paths"][0]["nodes"]] == ["Me", "Target", "Far"]
    assert out["paths"][0]["links"][1]["label"] == "Know each other"


def test_tags_change_on_several_people_at_once(client):
    ana, ben, cy = people(client, "Ana", "Ben", "Cy")
    r = client.post("/api/crm/network/tags", json={"ids": [ana["id"], ben["id"], cy["id"]], "add": ["Hardware", "needs follow up"]})
    assert r.json() == {"changed": 3}
    assert client.post("/api/crm/network/tags", json={"ids": [ana["id"]], "add": ["hardware"]}).json() == {"changed": 0}
    client.post("/api/crm/network/tags", json={"ids": [ben["id"]], "remove": ["hardware"]})
    tags = {t["tag"]: t["count"] for t in client.get("/api/crm/network/tags").json()}
    assert tags == {"hardware": 2, "needs-follow-up": 3}
    assert {g["name"] for g in net_json(client)["groups"]} == {"hardware", "needs follow up"}
    assert client.post("/api/crm/network/tags", json={"ids": []}).status_code == 422


def test_saved_views_remember_which_groups_were_on(client):
    for row in client.get("/api/crm/network/views").json():
        client.delete(f"/api/crm/network/views/{row['id']}")
    v = client.post("/api/crm/network/views", json={"name": "Hardware mentors", "wells": ["tag:hardware", "tag:mentor"]}).json()
    again = client.post("/api/crm/network/views", json={"name": "hardware MENTORS", "wells": ["tag:hardware"]}).json()
    assert again["id"] == v["id"] and again["wells"] == ["tag:hardware"]  # same name: replaced, not duplicated
    assert [x["name"] for x in client.get("/api/crm/network/views").json()] == ["hardware MENTORS"]
    assert client.delete(f"/api/crm/network/views/{v['id']}").status_code == 204
    assert client.delete(f"/api/crm/network/views/{v['id']}").status_code == 404
