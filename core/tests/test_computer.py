"""Which system this is, its words, and what the shell around the app says it can do (core/server/computer.py)."""
from core.server import computer, config


def test_a_browser_has_no_shell_and_can_do_nothing(monkeypatch):
    monkeypatch.delenv(f"{config.PREFIX}_SHELL", raising=False)
    monkeypatch.delenv("APP_SHELL", raising=False)
    monkeypatch.setenv("APP_SHELL_CAN", "quit,reveal")
    assert computer.shell() is None
    assert computer.can() == []


def test_the_shell_names_itself_and_what_it_can_do(monkeypatch):
    monkeypatch.setenv("APP_SHELL", "desktop")
    monkeypatch.setenv("APP_SHELL_CAN", " Reveal,quit,,updates ")
    assert computer.info()["shell"] == "desktop"
    assert computer.can() == ["quit", "reveal", "updates"]


def test_every_system_has_every_word():
    keys = set(computer._WORDS["mac"])
    assert {"here", "files", "tray", "app", "apps", "terminal"} <= keys
    for os_name, words in computer._WORDS.items():
        assert set(words) == keys, os_name


def test_the_app_info_tells_the_web_app(client):
    info = client.get("/api/app").json()["computer"]
    assert info["os"] in ("mac", "windows", "linux")
    assert info["words"]["here"]
