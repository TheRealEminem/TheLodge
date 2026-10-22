"""Network presets: focused questions answered as a list of people with reasons, saved presets, and lists the AI
writes from what you ask for."""
import pytest
from crm_helpers import link, make

from core.server import ai, jobs
from modules.crm.server import presets, profiles

READY = {"provider": "gemini", "label": "Gemini", "model": "flash", "ready": True, "reason": "", "local": False}


@pytest.fixture
def ready(monkeypatch):
    monkeypatch.setattr(profiles, "provider", lambda: dict(READY))


@pytest.fixture
def book(client):
    """You know Ana well and Ben a little; Ana and Ben work at Acme, Cy used to; Dee knows Eve, who you don't know."""
    me = client.put("/api/crm/me", json={"name": "Me"}).json()
    ana = make(client, "person", "Ana", attributes={"title": "Angel Investor"}, tags=["mentor", "Northwest Innovation Showcase"])
    ben = make(client, "person", "Ben", tags=["prospect"], summary="Runs cold chain pilots for vaccine clinics.")
    cy = make(client, "person", "Cy", attributes={"connection_stage": "Met at event"})
    dee = make(client, "person", "Dee", tags=["mentor"])
    eve = make(client, "person", "Eve")
    acme = make(client, "organization", "Acme")
    link(client, me, "knows", ana, strength=5)
    link(client, me, "knows", ben, strength=2)
    link(client, me, "knows", dee, strength=3)
    link(client, ana, "works_at", acme)
    link(client, ben, "works_at", acme)
    link(client, cy, "works_at", acme, ended_at="2020-01-01")
    link(client, dee, "knows", eve, strength=4)
    link(client, ana, "invested_in", acme)
    return {"me": me, "ana": ana, "ben": ben, "cy": cy, "dee": dee, "eve": eve, "acme": acme}


def run(client, **spec):
    r = client.post("/api/crm/network/presets/run", json=spec)
    assert r.status_code == 200, r.text
    return r.json()


def names(result):
    return [p["name"] for p in result["people"]]


def why(result, name):
    return next(p["why"] for p in result["people"] if p["name"] == name)


def test_who_you_know_at_an_organization_includes_former_staff_and_ranks_the_closest_first(client, book):
    out = run(client, kind="at", group=f"org:{book['acme']['id']}")
    assert out["title"] == "Who you know at Acme"
    assert names(out) == ["Ana", "Ben", "Cy"]
    assert why(out, "Ana") == ["Works there", "Invested in them"] and why(out, "Cy") == ["Used to work there"]


def test_who_you_know_in_a_tag_or_topic_uses_its_members(client, book):
    out = run(client, kind="at", group="tag:mentor")
    assert out["title"] == "Who you know in mentor" and names(out) == ["Ana", "Dee"] and why(out, "Dee") == ["Tagged mentor"]
    assert client.post("/api/crm/network/presets/run", json={"kind": "at", "group": "nope:1"}).status_code == 400


def test_who_could_introduce_you_to_a_person_is_only_people_you_know_who_know_them(client, book):
    out = run(client, kind="intro", target=book["eve"]["id"])
    assert out["title"] == "Who could introduce you to Eve"
    assert names(out) == ["Dee"] and why(out, "Dee") == ["Knows Eve"]


def test_who_could_introduce_you_to_an_organization_starts_with_people_there_then_people_who_know_them(client, book):
    link(client, book["dee"], "knows", book["ben"])
    out = run(client, kind="intro", target=book["acme"]["id"])
    assert names(out)[:2] == ["Ana", "Ben"]  # inside, the one you know best first
    assert why(out, "Ana") == ["Works at Acme"] and why(out, "Dee") == ["Knows Ben"]
    assert "Cy" not in names(out)  # you don't know Cy, and Cy has left


def test_an_introducers_reason_is_said_from_their_side(client, book):
    meeting = make(client, "meeting", "Pilot call")
    link(client, book["eve"], "attended", meeting)
    link(client, book["ben"], "discussed_in", meeting)
    out = run(client, kind="intro", target=book["eve"]["id"])
    assert why(out, "Ben") == ["Came up in Pilot call, with Eve"]


def test_you_cant_ask_for_an_introduction_to_yourself(client, book):
    r = client.post("/api/crm/network/presets/run", json={"kind": "intro", "target": book["me"]["id"]})
    assert r.status_code == 400 and r.json()["detail"] == "That's you"


def test_investors_and_advisors_come_from_titles_ties_and_tags(client, book):
    link(client, book["dee"], "advises", book["me"])
    client.patch(f"/api/crm/entities/{book['eve']['id']}", json={"tags": ["investor-healthcare-vc"]})
    out = run(client, kind="investors")
    assert set(names(out)) == {"Ana", "Dee", "Eve"}
    assert why(out, "Ana") == ["Angel Investor", "Invested in Acme"]
    assert why(out, "Dee") == ["Advises you"] and why(out, "Eve") == ["Tagged investor healthcare vc"]


def test_everyone_from_an_event_includes_meetings_of_the_same_name_and_its_tag(client, book):
    show = make(client, "meeting", "Northwest Innovation Showcase")
    again = make(client, "meeting", "Northwest Innovation Showcase 2027 planning")
    link(client, book["ben"], "attended", show)
    link(client, book["dee"], "attended", again)
    link(client, book["eve"], "discussed_in", show)
    out = run(client, kind="event", event=show["id"])
    assert set(names(out)) == {"Ana", "Ben", "Dee", "Eve"}
    assert why(out, "Ana") == ["Tagged northwest innovation showcase"]
    assert why(out, "Eve") == ["Came up in Northwest Innovation Showcase"]
    assert "1 more with the same name" in out["about"]


def test_bridges_are_the_people_in_both_groups(client, book):
    out = run(client, kind="bridges", a=f"org:{book['acme']['id']}", b="tag:mentor")
    assert names(out) == ["Ana"] and why(out, "Ana") == ["Acme: works there", "mentor: tagged"]
    assert client.post("/api/crm/network/presets/run", json={"kind": "bridges", "a": "tag:mentor", "b": "tag:mentor"}).status_code == 400


def test_follow_ups_are_tagged_or_staged_people_not_yet_met_or_rated(client, book):
    out = run(client, kind="followups")
    assert set(names(out)) == {"Ben", "Cy"}
    assert why(out, "Cy") == ["Met at event", "No meeting together yet", "You haven't rated them"]
    assert why(out, "Ben")[0] == "Tagged prospect"


def test_a_rule_matches_tags_organizations_words_and_picks(client, book):
    out = run(client, kind="rule", name="Cold chain", tags=["mentor"], organizations=[book["acme"]["id"]], words=["cold chain"],
              picks=[{"id": book["eve"]["id"], "why": "Talked about freezers"}, {"id": "nobody", "why": "x"}])
    assert out["title"] == "Cold chain"
    assert set(names(out)) == {"Ana", "Ben", "Cy", "Dee", "Eve"}
    assert why(out, "Ben") == ["Works at Acme", "Their summary mentions “cold chain”"]
    assert why(out, "Eve") == ["Talked about freezers"]


def test_saving_a_preset_keeps_it_by_name_and_it_runs_fresh(client, book):
    r = client.post("/api/crm/network/presets", json={"name": "Acme people", "spec": {"kind": "at", "group": f"org:{book['acme']['id']}"}})
    assert r.status_code == 201, r.text
    again = client.post("/api/crm/network/presets", json={"name": "acme people", "about": "Again", "spec": {"kind": "investors"}}).json()
    saved = client.get("/api/crm/network/presets").json()
    assert len(saved) == 1 and saved[0]["id"] == again["id"] and saved[0]["spec"] == {"kind": "investors"}
    bad = client.post("/api/crm/network/presets", json={"name": "Odd", "spec": {"kind": "wat"}})
    assert bad.status_code == 400
    assert client.delete(f"/api/crm/network/presets/{again['id']}").status_code == 204
    assert client.get("/api/crm/network/presets").json() == []


def test_choices_list_small_groups_and_meetings_with_people(client, book):
    show = make(client, "meeting", "Showcase")
    make(client, "meeting", "Empty room")
    link(client, book["ben"], "attended", show)
    c = client.get("/api/crm/network/presets/choices").json()
    assert {g["name"] for g in c["groups"]} >= {"Acme", "mentor", "prospect"}  # prospect has one person: still a choice
    assert [e["name"] for e in c["events"]] == ["Showcase"]


def idea(**extra):
    base = dict(name="", about="", tags=[], topics=[], organizations=[], events=[], words=[], picks=[])
    return presets.Idea(**{**base, **extra})


def test_asking_the_ai_for_a_list_keeps_what_finds_people_and_drops_made_up_ids(client, book, ready, fake_structured):
    fake_structured.reply = presets.Ideas(presets=[
        idea(name="Cold-chain help", about="People who know cold chain.", words=["cold chain"], organizations=["made-up"],
             picks=[presets.Pick(id=book["eve"]["id"], why="Knows freezer makers"), presets.Pick(id="ghost", why="?")]),
        idea(name="Nobody", about="Finds no one.", tags=["no-such-tag"]),
    ])
    r = client.post("/api/crm/network/presets/asks", json={"request": "everyone who could help with cold-chain funding"})
    assert r.status_code == 202, r.text
    jobs.drain()
    asked = client.get("/api/crm/network/presets/asks").json()[0]
    assert asked["status"] == "done" and len(asked["ideas"]) == 1
    got = asked["ideas"][0]
    assert got["name"] == "Cold-chain help" and got["count"] == 2 and set(got["sample"]) == {"Ben", "Eve"}
    assert got["spec"]["organizations"] == [] and [p["id"] for p in got["spec"]["picks"]] == [book["eve"]["id"]]
    call = fake_structured.calls[0]
    assert call["choice"] == "auto" and "everyone who could help with cold-chain funding" in call["prompt"]
    assert book["ben"]["id"] in call["prompt"] and "Runs cold chain pilots" in call["prompt"] and "mentor: 2" in call["prompt"]


def test_with_no_request_the_ai_suggests_presets_and_is_told_what_is_built_in(client, book, ready, fake_structured):
    fake_structured.reply = presets.Ideas(presets=[idea(name="Mentors", about="Your mentors.", tags=["mentor"])])
    client.post("/api/crm/network/presets/asks", json={})
    jobs.drain()
    asked = client.get("/api/crm/network/presets/asks").json()[0]
    assert asked["request"] == "" and asked["ideas"][0]["count"] == 2
    assert "don't repeat them" in fake_structured.calls[0]["prompt"]


def test_an_ai_failure_is_kept_on_the_ask_and_no_ai_means_no_ask(client, book, ready, fake_structured, monkeypatch):
    fake_structured.reply = ai.AIError("The key was refused")
    client.post("/api/crm/network/presets/asks", json={"request": "funders"})
    jobs.drain()
    asked = client.get("/api/crm/network/presets/asks").json()[0]
    assert asked["status"] == "error" and asked["error"] == "The key was refused"
    assert client.delete(f"/api/crm/network/presets/asks/{asked['id']}").status_code == 204
    assert client.get("/api/crm/network/presets/asks").json() == []
    monkeypatch.setattr(profiles, "provider", lambda: {**READY, "ready": False, "reason": "Add an API key"})
    r = client.post("/api/crm/network/presets/asks", json={"request": "funders"})
    assert r.status_code == 400 and r.json()["detail"] == "Add an API key"


def test_only_the_last_few_asks_are_kept(client, book, ready, fake_structured):
    fake_structured.reply = presets.Ideas(presets=[])
    for i in range(presets.KEEP_ASKS + 2):
        client.post("/api/crm/network/presets/asks", json={"request": f"list {i}"})
    jobs.drain()
    assert len(client.get("/api/crm/network/presets/asks").json()) == presets.KEEP_ASKS
