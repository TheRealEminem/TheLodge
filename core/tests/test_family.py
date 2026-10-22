"""The family link: shared keys and preferences, the registry of installed apps, and app-to-app calls, against a
throwaway family folder (conftest.py sets TRAILMIX_FAMILY_DIR)."""
import json
import os

import httpx
import pytest

from core.server import config, db, family, module, settings


@pytest.fixture(autouse=True)
def fresh_family():
    def wipe():
        with family._connect() as conn:
            for table in ("family_settings", "family_apps", "family_meta"):
                conn.execute(f"DELETE FROM {table}")
        db.execute("DELETE FROM core_settings WHERE key LIKE 'ai.%' OR key LIKE 'core.%'")
    wipe()
    yield
    wipe()


def another_app_saves(changes: dict) -> None:
    """What another family app ("Faraway") does when you save a shared setting there."""
    with family._connect() as conn:
        for key, value in changes.items():
            conn.execute("INSERT INTO family_settings (key, value, updated_at, updated_by) VALUES (?, ?, 'now', 'faraway') "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, json.dumps(value)))
        family._bump(conn)


# A stand-in module with offers, so calls can be tested without the app's real modules.
module.register(module.Module(id="probe3", name="Probe three",
                              offers={"probe.echo": lambda args: {"heard": args}, "probe.fail": lambda args: args["missing"]}))


# ── Shared keys and preferences ───────────────────────────────────────

def test_a_key_saved_here_is_there_for_every_family_app():
    settings.update({"ai.anthropic_api_key": " sk-ant-shared-123456 ", "core.your_name": "Sam"})
    assert family.values() == {"ai.anthropic_api_key": "sk-ant-shared-123456", "core.your_name": "Sam"}


def test_a_preference_saved_in_another_app_shows_here(client):
    another_app_saves({"core.your_name": "Sam", "core.appearance": "dusk", "ai.provider": "anthropic"})
    values = client.get("/api/settings").json()["values"]
    assert (values["core.your_name"], values["core.appearance"], values["ai.provider"]) == ("Sam", "dusk", "anthropic")


def test_keys_stay_write_only_even_when_shared(client):
    another_app_saves({"ai.openai_api_key": "sk-openai-from-faraway-9876"})
    body = client.get("/api/settings").json()
    assert body["values"]["ai.openai_api_key"] == "" and body["secret_hints"]["ai.openai_api_key"] == "…9876"
    assert settings.section("ai")["openai_api_key"] == "sk-openai-from-faraway-9876"     # the server can use it


def test_only_the_listed_settings_are_shared():
    settings.update({"core.share_with_family": True, "core.appearance": "light"})
    assert set(family.values()) == {"core.appearance"}                    # the sharing switch itself stays here
    assert family.is_shared("ai.gemini_model") and not family.is_shared("tasks.anything")


def test_an_app_that_stops_sharing_keeps_its_own():
    settings.update({"core.your_name": "Sam"})
    settings.update({"core.share_with_family": False})
    another_app_saves({"core.your_name": "Someone else"})
    assert settings.get_all()["core.your_name"] == "Sam"
    settings.update({"core.your_name": "Sam M"})
    assert family.values()["core.your_name"] == "Someone else"            # nothing it saves leaves it either
    settings.update({"core.share_with_family": True})
    assert settings.get_all()["core.your_name"] == "Someone else"         # back on: the family's value again


def test_joining_fills_in_what_the_family_lacks_and_never_replaces_it():
    db.execute("INSERT INTO core_settings (key, value) VALUES ('ai.gemini_api_key', '\"g-local-key-1111\"')")
    db.execute("INSERT INTO core_settings (key, value) VALUES ('core.your_name', '\"Local name\"')")
    another_app_saves({"core.your_name": "Family name"})
    assert family.seed(settings.stored_here()) == ["ai.gemini_api_key"]
    assert family.values() == {"ai.gemini_api_key": "g-local-key-1111", "core.your_name": "Family name"}


def test_open_screens_refresh_when_another_app_changes_a_shared_setting(client):
    before = client.get("/api/changes").json()["seq"]
    another_app_saves({"core.appearance": "dusk"})
    assert client.get("/api/changes").json()["seq"] > before


def test_with_the_link_off_settings_are_this_apps_own(monkeypatch):
    monkeypatch.setenv("TRAILMIX_FAMILY_DIR", "off")
    assert not family.enabled() and family.values() == {} and family.apps() == []
    settings.update({"core.your_name": "Only here"})
    assert settings.get_all()["core.your_name"] == "Only here"
    with pytest.raises(family.Unavailable):
        family.token()


def test_the_mac_app_joins_by_default_and_a_development_copy_does_not(monkeypatch, tmp_path):
    monkeypatch.delenv("TRAILMIX_FAMILY_DIR")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    assert family.folder() is None
    monkeypatch.setattr(config, "DATA_DIR", family.DEFAULT_DIR.parent / config.NAME)
    assert family.folder() == family.DEFAULT_DIR


# ── Who's installed ───────────────────────────────────────────────────

def test_an_app_registers_with_its_port_and_offers(client):
    family.register(port=8888)
    [me] = family.apps()
    assert (me["id"], me["port"], me["running"], me["self"]) == (config.APP_ID, 8888, True, True)
    assert "probe.echo" in me["offers"]
    status = client.get("/api/family").json()
    assert status["enabled"] and status["sharing"] and [a["id"] for a in status["apps"]] == [config.APP_ID]


def test_a_closed_app_is_still_listed_but_not_running():
    family.register()
    family.leave()
    with family._connect() as conn:
        conn.execute("INSERT INTO family_apps VALUES ('faraway', 'Faraway', '0.1.0', 8791, 999999, '[]', '/x', 'now', ?)",
                     (family._now(),))
    apps = {a["id"]: a for a in family.apps()}
    assert not apps[config.APP_ID]["running"] and not apps["faraway"]["running"]


# ── Asking another app ────────────────────────────────────────────────
# "faraway.search" stands for an offer only another app has, whatever modules this app runs.

def test_a_call_needs_the_family_token(client):
    assert client.post("/api/family/call/probe.echo", json={"q": "ana"}).status_code == 403
    assert client.post("/api/family/call/probe.echo", json={}, headers={family.TOKEN_HEADER: "guess"}).status_code == 403
    ok = client.post("/api/family/call/probe.echo", json={"q": "ana"}, headers={family.TOKEN_HEADER: family.token()})
    assert ok.status_code == 200 and ok.json() == {"result": {"heard": {"q": "ana"}}}


def test_a_call_for_something_this_app_doesnt_offer_says_so(client):
    r = client.post("/api/family/call/faraway.search", json={}, headers={family.TOKEN_HEADER: family.token()})
    assert r.status_code == 404 and "doesn't offer faraway.search" in r.json()["detail"]
    bad = client.post("/api/family/call/probe.fail", json={}, headers={family.TOKEN_HEADER: family.token()})
    assert bad.status_code == 400


def test_an_apps_own_offers_answer_without_leaving_it(monkeypatch):
    monkeypatch.setattr(family, "_post", lambda *a, **k: pytest.fail("shouldn't leave the app"))
    assert family.call("probe.echo", q="ana") == {"heard": {"q": "ana"}}


def test_another_running_app_answers_through_localhost(client, monkeypatch):
    with family._connect() as conn:
        conn.execute("INSERT INTO family_apps VALUES ('faraway', 'Faraway', '0.1.0', 8791, ?, '[\"faraway.search\"]', '/x', 'now', ?)",
                     (os.getpid(), family._now()))
    sent = {}

    def faraway(url, body, headers, timeout):
        sent.update(url=url, body=body, token=headers[family.TOKEN_HEADER])
        return httpx.Response(200, json={"result": [{"ref": "faraway:1", "name": "Ana Ruiz"}]})

    monkeypatch.setattr(family, "_post", faraway)
    assert family.call("faraway.search", q="ana") == [{"ref": "faraway:1", "name": "Ana Ruiz"}]
    assert sent == {"url": "http://127.0.0.1:8791/api/family/call/faraway.search", "body": {"q": "ana"}, "token": family.token()}


def test_when_no_app_can_answer_the_message_says_what_to_do(monkeypatch):
    with pytest.raises(family.Unavailable, match="None of your family apps"):
        family.call("faraway.search", q="ana")
    with family._connect() as conn:
        conn.execute("INSERT INTO family_apps VALUES ('faraway', 'Faraway', '0.1.0', 8791, NULL, '[\"faraway.search\"]', '/x', 'now', ?)",
                     (family._now(),))
    with pytest.raises(family.Unavailable, match="Open Faraway to see this here"):
        family.call("faraway.search", q="ana")
    with family._connect() as conn:
        conn.execute("UPDATE family_apps SET pid = ? WHERE id = 'faraway'", (os.getpid(),))
    monkeypatch.setattr(family, "_post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("refused")))
    with pytest.raises(family.Unavailable, match="Faraway didn't answer"):
        family.call("faraway.search", q="ana")
