"""Pictures of people: added by hand, kept with a merge, gone with the person, and looked up only when allowed."""
import base64

from core.server import jobs, settings
from crm_helpers import make

from modules.crm.server import pictures, store

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg==")


def put(client, who, body=PNG):
    return client.put(f"/api/crm/pictures/{who['id']}", content=body)


def test_a_picture_is_kept_served_and_listed(client):
    ana = make(client, "person", "Ana Ruiz")
    assert client.get("/api/crm/pictures").json() == {}
    assert put(client, ana).status_code == 204
    versions = client.get("/api/crm/pictures").json()
    assert list(versions) == [ana["id"]]
    got = client.get(f"/api/crm/pictures/{ana['id']}")
    assert got.status_code == 200 and got.content == PNG and got.headers["content-type"] == "image/png"
    again = client.get(f"/api/crm/pictures/{ana['id']}", headers={"If-None-Match": got.headers["etag"]})
    assert again.status_code == 304
    assert client.delete(f"/api/crm/pictures/{ana['id']}").status_code == 204
    assert client.get(f"/api/crm/pictures/{ana['id']}").status_code == 404


def test_only_pictures_are_taken(client):
    ana = make(client, "person", "Ana Ruiz")
    assert put(client, ana, b"<html>not a picture</html>").status_code == 422
    assert put(client, ana, b"").status_code == 422
    assert put(client, ana, PNG + b"0" * pictures.MAX_BYTES).status_code == 422
    assert put(client, {"id": "nobody"}).status_code == 404
    assert client.get("/api/crm/pictures").json() == {}


def test_deleting_a_person_removes_the_picture(client):
    ana = make(client, "person", "Ana Ruiz")
    put(client, ana)
    client.delete(f"/api/crm/entities/{ana['id']}")
    assert client.get("/api/crm/pictures").json() == {}


def test_a_merge_keeps_a_picture_the_survivor_lacks(client):
    keep, other = make(client, "person", "Jordan Reyes"), make(client, "person", "Jordon Reyes")
    put(client, other)
    store.merge_entities(other["id"], keep["id"])
    assert list(client.get("/api/crm/pictures").json()) == [keep["id"]]
    mine = make(client, "person", "Bob Lee")
    theirs = make(client, "person", "Robert Lee")
    put(client, mine)
    put(client, theirs, PNG + b"\0")
    store.merge_entities(theirs["id"], mine["id"])
    assert client.get(f"/api/crm/pictures/{mine['id']}").content == PNG       # the survivor's own wins


def test_lookup_is_off_until_allowed_and_asks_with_a_hash_not_the_address(client, monkeypatch):
    ana = make(client, "person", "Ana Ruiz", attributes={"email": "Ana@Helio.example"})
    assert client.post(f"/api/crm/people/{ana['id']}/picture/lookup").status_code == 422
    assert client.post("/api/crm/pictures/lookup").status_code == 422
    assert client.get("/api/crm/pictures/lookup").json()["allowed"] is False

    settings.update({pictures.SETTING: True})
    asked = []

    class Reply:
        status_code, content = 200, PNG
        def raise_for_status(self): pass

    class Client:
        def __init__(self, **kw): pass
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def get(self, url):
            asked.append(url)
            return Reply()

    monkeypatch.setattr(pictures.httpx, "Client", Client)
    try:
        assert client.post(f"/api/crm/people/{ana['id']}/picture/lookup").json() == {"found": True}
        assert pictures.get(ana["id"])[1] == "image/png"
        assert "@" not in asked[0] and pictures._email_hash("ana@helio.example") in asked[0]   # case and spaces don't matter
    finally:
        settings.update({pictures.SETTING: False})


def test_everyone_without_a_picture_is_asked_in_the_background(client, monkeypatch):
    with_email = make(client, "person", "Ana Ruiz", attributes={"email": "ana@helio.example"})
    has_one = make(client, "person", "Bob Lee", attributes={"email": "bob@helio.example"})
    make(client, "person", "No Email")
    put(client, has_one)
    settings.update({pictures.SETTING: True})
    seen = []
    monkeypatch.setattr(pictures, "_fetch", lambda client, email: seen.append(email) or (PNG if email.startswith("ana") else None))
    try:
        assert client.post("/api/crm/pictures/lookup").status_code == 202
        jobs.drain()
    finally:
        settings.update({pictures.SETTING: False})
    assert seen == ["ana@helio.example"]
    assert set(client.get("/api/crm/pictures").json()) == {with_email["id"], has_one["id"]}
