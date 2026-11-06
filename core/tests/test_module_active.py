"""A connection to an outside tool (Module.active) is off until it's set up: its pages and tools stay out of the app and
its settings stay in. Whether first run has been answered is setup.py's (test_setup.py)."""
import pytest

from core.server import mcp, module


@pytest.fixture
def link():
    """A stand-in connection that is on only while `link.on` is True."""
    class Link:
        on = False

    state = Link()
    tool = mcp.Tool(name="look", title="Look", description="Look.", handler=lambda args: {"ok": True})
    module.register(module.Module(id="link", name="Link", tools=[tool], active=lambda: state.on))
    yield state
    module._loaded.pop("link", None)


def test_the_app_says_which_modules_are_connections_and_which_are_on(client, link):
    mods = {m["id"]: m for m in client.get("/api/app").json()["modules"]}
    assert mods["link"] == {"id": "link", "name": "Link", "optional": True, "active": False}
    assert mods["probe"]["optional"] is False and mods["probe"]["active"] is True
    link.on = True
    assert {m["id"]: m for m in client.get("/api/app").json()["modules"]}["link"]["active"] is True
    assert [m.id for m in module.active_modules()][-1] == "link"
def test_claude_sees_a_connections_tools_only_once_it_is_on(link):
    assert "link_look" not in [name for name, _, _ in mcp.tools()]
    link.on = True
    assert "link_look" in [name for name, _, _ in mcp.tools()]
