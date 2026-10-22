"""The people directory (people.py): every module's people and other family apps', merged, with you as core:me.
Uses stand-in modules and a stand-in family, so it passes whatever modules and apps there are."""
import pytest

from core.server import family, module, people, settings


def provider(*rows):
    return lambda q, limit: [r for r in rows if q.lower() in r["name"].lower() or q.lower() in (r.get("email") or "")][:limit]


CREW = provider(
    {"id": "c1", "name": "Ana Ruiz", "email": "ana@example.org", "detail": "Crew"},
    {"id": "c2", "name": "Alex Rivera", "email": "sam@example.org", "is_self": True},
    {"id": "c3", "name": "Dana Banana", "email": None},
)
GUILD = provider(
    {"id": "g1", "name": "Anabel Lee", "email": "anabel@example.org", "detail": "Guild"},
    {"id": "g2", "name": "Ana R.", "email": "ANA@example.org"},              # Ana again, by her email
    {"id": "g3", "name": "Me Myself", "is_self": True},
)


@pytest.fixture
def directory(monkeypatch):
    """Two stand-in modules that know people, and no family app unless a test adds one."""
    monkeypatch.setattr(module, "_loaded", {
        "crew": module.Module(id="crew", name="Crew", people=CREW),
        "guild": module.Module(id="guild", name="Guild", people=GUILD),
        "quiet": module.Module(id="quiet", name="Quiet"),
    })
    monkeypatch.setattr(family, "apps", lambda: [])
    settings.update({"core.your_name": ""})
    yield monkeypatch
    settings.update({"core.your_name": ""})


def refs(found):
    return [p["ref"] for p in found["people"]]


def test_every_modules_people_are_merged_with_their_refs(directory):
    found = people.find("ana")
    assert refs(found) == ["crew:c1", "guild:g1", "crew:c3"]
    assert found["people"][0] == {"ref": "crew:c1", "name": "Ana Ruiz", "email": "ana@example.org", "detail": "Crew",
                                  "module": "crew"}
    assert found["note"] is None


def test_names_that_start_with_the_search_come_first(directory):
    # "Ana Ruiz" and "Anabel Lee" start with "ana"; "Dana Banana" only contains it.
    assert [p["name"] for p in people.find("ana")["people"]] == ["Ana Ruiz", "Anabel Lee", "Dana Banana"]
    assert [p["name"] for p in people.find("lee")["people"]] == ["Anabel Lee"]


def test_you_are_core_me_once_first_and_named_from_settings(directory):
    settings.update({"core.your_name": "Sam"})
    found = people.find("m")
    assert refs(found)[0] == "core:me" and refs(found).count("core:me") == 1
    assert found["people"][0] == {"ref": "core:me", "name": "Sam", "email": "sam@example.org", "detail": "You",
                                  "module": "core"}
    assert "crew:c2" not in refs(found) and "guild:g3" not in refs(found)    # never a module's own record of you


def test_an_empty_search_is_you_then_everyone(directory):
    assert refs(people.find("")) == ["core:me", "crew:c1", "guild:g1", "crew:c3"]
    assert people.find("")["people"][0]["name"] == "You"
    assert refs(people.find("you")) == ["core:me"]


def test_the_same_email_shows_once_as_the_first_place_that_knows_them(directory):
    found = people.find("ana r")
    assert refs(found) == ["crew:c1"]                                     # not guild:g2 too


def test_the_limit_holds_after_merging(directory):
    assert len(people.find("a", limit=2)["people"]) == 2


def test_one_broken_directory_doesnt_hide_the_others(directory):
    def broken(q, limit):
        raise RuntimeError("boom")
    module._loaded["crew"] = module.Module(id="crew", name="Crew", people=broken)
    assert refs(people.find("ana")) == ["guild:g2", "guild:g1"]        # Ana is only Guild's now


def test_people_in_another_family_app_come_too(directory):
    directory.setattr(family, "apps", lambda: [
        {"id": "lodge", "name": "The Lodge", "offers": ["people.search"], "self": False, "running": True}])
    asked = []

    def call(offer, timeout=5.0, **args):
        asked.append((offer, args, timeout))
        return [{"ref": "crm:9a1c", "name": "Ana Bell", "email": None, "detail": "Designer", "href": "#/crm/e/9a1c"},
                {"ref": "crm:5b2e", "name": "Ana Ruiz", "email": "ana@example.org"}]        # known here already
    directory.setattr(family, "call", call)
    found = people.find("ana")
    assert asked == [("people.search", {"q": "ana", "limit": 8}, people.FAMILY_TIMEOUT)]
    assert refs(found) == ["crm:9a1c", "crew:c1", "guild:g1", "crew:c3"]
    assert next(p for p in found["people"] if p["ref"] == "crm:9a1c")["module"] == "family"


def test_when_that_app_is_closed_the_local_people_still_come_with_a_sentence(directory):
    directory.setattr(family, "apps", lambda: [
        {"id": "lodge", "name": "The Lodge", "offers": ["people.search"], "self": False, "running": False}])

    def closed(offer, timeout=5.0, **args):
        raise family.Unavailable("Open The Lodge to see this here.")
    directory.setattr(family, "call", closed)
    found = people.find("ana")
    assert refs(found) == ["crew:c1", "guild:g1", "crew:c3"]
    assert found["note"] == "Open The Lodge to see this here."


def test_no_family_app_that_knows_people_means_no_call_and_no_note(directory):
    directory.setattr(family, "call", lambda *a, **k: pytest.fail("asked the family for nothing"))
    assert people.find("ana")["note"] is None


def test_by_email_finds_the_one_person(directory):
    assert people.by_email("ANA@example.org") == "crew:c1"
    assert people.by_email("nobody@example.org") is None
    assert people.by_email("") is None


def test_the_people_endpoint(directory, client):
    body = client.get("/api/people", params={"q": "ana", "limit": 2}).json()
    assert body == {"people": [
        {"ref": "crew:c1", "name": "Ana Ruiz", "email": "ana@example.org", "detail": "Crew", "module": "crew"},
        {"ref": "guild:g1", "name": "Anabel Lee", "email": "anabel@example.org", "detail": "Guild", "module": "guild"},
    ], "note": None}
