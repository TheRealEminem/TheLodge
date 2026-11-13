"""The MCP server (mcp.py): the protocol over /mcp, the token, refusing web pages, Settings → Claude, the bridge for
Claude Desktop, and that a tool can never start work that waits for your approval. Tools come from the stand-in
module, so these pass whatever modules the app has."""
import json
import os
import subprocess
import sys
import urllib.error

import pytest

from core.server import config, jobs, mcp, module, settings
from core.server.mcp import Tool
from core.server import mcp_bridge

calls: list[dict] = []


def _echo(args: dict) -> dict:
    calls.append(args)
    if args.get("word") == "no":
        raise ValueError("The probe won't say no.")
    if args.get("word") == "boom":
        raise RuntimeError("a bug")
    return {"said": args.get("word", ""), "times": args.get("times", 1)}


def _approve(args: dict) -> str:
    jobs.go(args["job"])
    return "started"


PROBE_TOOLS = [
    Tool(name="echo", title="Echo", description="Says it back.", handler=_echo,
         params={"word": {"type": "string"}, "times": {"type": "integer"}, "loud": {"type": "boolean"},
                 "tone": {"type": "string", "enum": ["soft", "plain"]}}),
    Tool(name="approve", title="Approve", description="Tries to start waiting work.", handler=_approve, writes=True,
         params={"job": {"type": "string"}}, required=("job",)),
]


@pytest.fixture
def probe_tools(monkeypatch):
    monkeypatch.setattr(module.get("probe"), "tools", PROBE_TOOLS)
    calls.clear()


@pytest.fixture
def token(client):
    """Claude's access turned on; the token, as the commands to copy carry it. Turned off afterwards."""
    r = client.post("/api/mcp/token")
    assert r.status_code == 200
    yield _token_in(r.json()["setup"])
    client.delete("/api/mcp/token")


def _token_in(setup: dict) -> str:
    return setup["claude_code"].rsplit("Bearer ", 1)[1].rstrip('"')


def _rpc(client, token, method, params=None, rid=1, headers=None):
    body = {"jsonrpc": "2.0", "id": rid, "method": method}
    if params is not None:
        body["params"] = params
    return client.post("/mcp", json=body, headers={"Authorization": f"Bearer {token}", **(headers or {})})


def _call(client, token, name, **args) -> dict:
    r = _rpc(client, token, "tools/call", {"name": name, "arguments": args})
    assert r.status_code == 200, r.text
    return r.json()["result"]


# ── The protocol ──────────────────────────────────────────────────────

def test_initialize_agrees_a_version_and_says_what_it_is(client, token):
    r = _rpc(client, token, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                           "clientInfo": {"name": "claude-code", "version": "2"}})
    result = r.json()["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"] == {"tools": {"listChanged": False}}
    assert result["serverInfo"]["name"] == config.APP_ID and result["serverInfo"]["title"] == config.NAME
    assert "never approve anything" in result["instructions"]
    newer = _rpc(client, token, "initialize", {"protocolVersion": "2099-01-01"}).json()["result"]
    assert newer["protocolVersion"] == mcp.PROTOCOL_VERSIONS[0]      # one it speaks; the client decides


def test_notifications_get_202_and_unknown_methods_an_error(client, token):
    note = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"},
                       headers={"Authorization": f"Bearer {token}"})
    assert note.status_code == 202 and note.content == b""
    assert _rpc(client, token, "ping").json()["result"] == {}
    assert _rpc(client, token, "resources/list").json()["error"]["code"] == -32601
    bad = client.post("/mcp", content=b"{nope", headers={"Authorization": f"Bearer {token}"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == -32700
    assert client.post("/mcp", json={"id": 1, "method": "ping"},
                       headers={"Authorization": f"Bearer {token}"}).json()["error"]["code"] == -32600


def test_a_batch_answers_each_request(client, token):
    r = client.post("/mcp", headers={"Authorization": f"Bearer {token}"}, json=[
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}])
    assert [a["id"] for a in r.json()] == [1, 2]


def test_an_unknown_protocol_version_header_is_refused(client, token):
    assert _rpc(client, token, "ping", headers={"MCP-Protocol-Version": "1999-01-01"}).status_code == 400
    assert _rpc(client, token, "ping", headers={"MCP-Protocol-Version": "2025-06-18"}).status_code == 200


def test_get_and_delete_are_not_offered(client, token):
    for method in ("GET", "DELETE"):
        r = client.request(method, "/mcp", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 405 and r.headers["allow"] == "POST"


def test_tools_list_names_each_after_its_module(client, token, probe_tools):
    listed = {t["name"]: t for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    echo = listed["probe_echo"]
    assert echo["title"] == "Echo" and echo["description"] == "Says it back."
    assert echo["inputSchema"] == {"type": "object", "properties": PROBE_TOOLS[0].params, "required": [],
                                   "additionalProperties": False}
    assert echo["annotations"]["readOnlyHint"] is True
    approve = listed["probe_approve"]
    assert approve["annotations"]["readOnlyHint"] is False and approve["annotations"]["destructiveHint"] is False
    assert approve["inputSchema"]["required"] == ["job"]
    assert all(name.startswith(f"{owner.id}_") for name, owner, _ in mcp.tools())   # named after their module
    assert all(t["annotations"]["openWorldHint"] is False for t in listed.values())  # nothing leaves the app


def test_tools_call_runs_the_handler_and_answers_in_text(client, token, probe_tools):
    result = _call(client, token, "probe_echo", word="hello", times=2)
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"]) == {"said": "hello", "times": 2}
    assert calls == [{"word": "hello", "times": 2}]


def test_arguments_are_checked_before_the_handler_runs(client, token, probe_tools):
    for args, words in (({"times": "2"}, "times must be an integer"), ({"loud": 1}, "loud must be a boolean"),
                        ({"times": True}, "times must be an integer"), ({"tone": "loud"}, "tone must be one of soft"),
                        ({"colour": "red"}, "colour isn't something this tool takes")):
        result = _call(client, token, "probe_echo", **args)
        assert result["isError"] is True and words in result["content"][0]["text"], args
    missing = _call(client, token, "probe_approve")
    assert missing["isError"] is True and "Missing: job." in missing["content"][0]["text"]
    assert calls == []


def test_a_refusal_is_the_tools_sentence_and_a_bug_says_where_to_look(client, token, probe_tools):
    no = _call(client, token, "probe_echo", word="no")
    assert no == {"content": [{"type": "text", "text": "The probe won't say no."}], "isError": True}
    boom = _call(client, token, "probe_echo", word="boom")
    assert boom["isError"] is True and f"{config.NAME}'s log" in boom["content"][0]["text"]
    unknown = _rpc(client, token, "tools/call", {"name": "probe_nothing", "arguments": {}}).json()
    assert unknown["error"]["code"] == -32602


def test_a_tool_can_never_start_work_that_waits_for_you(client, token, probe_tools):
    ran = []
    jobs.register("probe", "careful", lambda job: ran.append(job.target))
    job_id = jobs.enqueue("probe", "careful", "t1", approve=True)
    result = _call(client, token, "probe_approve", job=job_id)
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Claude can't start work that waits for you. Only you can, in the app."
    jobs.drain()
    assert ran == [] and jobs.latest("probe", ["t1"])["t1"]["status"] == "waiting"
    assert mcp.calling() is None                                     # only while a tool runs
    jobs.go(job_id)                                                  # you still can
    jobs.drain()
    assert ran == ["t1"]


# ── Who may ask ───────────────────────────────────────────────────────

def test_off_until_a_token_is_made(client):
    client.delete("/api/mcp/token")
    assert client.get("/api/mcp").json()["on"] is False
    r = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 403 and "Settings → Claude" in r.json()["error"]["message"]


def test_the_token_is_checked(client, token):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    assert client.post("/mcp", json=ping).status_code == 401
    assert client.post("/mcp", json=ping, headers={"Authorization": f"Bearer {token}x"}).status_code == 401
    assert client.post("/mcp", json=ping, headers={"Authorization": token}).status_code == 401
    assert client.post("/mcp", json=ping, headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_web_pages_are_refused_even_with_the_token(client, token):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    auth = {"Authorization": f"Bearer {token}"}
    assert client.post("/mcp", json=ping, headers={**auth, "Origin": "https://example.com"}).status_code == 403
    assert client.post("/mcp", json=ping, headers={**auth, "Origin": "http://localhost:6274"}).status_code == 200


def test_a_new_token_replaces_the_old_and_turning_off_stops_both(client, token):
    ping = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    newer = _token_in(client.post("/api/mcp/token").json()["setup"])
    assert newer != token
    assert client.post("/mcp", json=ping, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.post("/mcp", json=ping, headers={"Authorization": f"Bearer {newer}"}).status_code == 200
    assert client.delete("/api/mcp/token").status_code == 204
    assert client.post("/mcp", json=ping, headers={"Authorization": f"Bearer {newer}"}).status_code == 403


def test_settings_show_the_token_once_then_only_its_end(client):
    made = client.post("/api/mcp/token").json()
    token = _token_in(made["setup"])
    assert len(token) >= 40
    assert made["on"] is True and made["hint"] == f"…{token[-4:]}"
    assert made["setup"]["claude_code"] == (f'claude mcp add --scope user --transport http {config.APP_ID} {mcp.url()} '
                                            f'--header "Authorization: Bearer {token}"')
    desktop = json.loads(made["setup"]["claude_desktop"])["mcpServers"][config.APP_ID]
    assert desktop == {"command": sys.executable, "args": ["-B", str(mcp.BRIDGE), mcp.url()], "env": {"MCP_TOKEN": token}}
    again = client.get("/api/mcp").json()
    assert token not in json.dumps(again) and again["hint"] == f"…{token[-4:]}"
    assert token not in json.dumps(client.get("/api/settings").json())
    assert settings.section("core")["mcp_token"] == token
    client.delete("/api/mcp/token")


# ── The bridge Claude Desktop runs ────────────────────────────────────

def test_the_bridge_passes_messages_through_with_the_token(client, token, probe_tools, monkeypatch):
    class Answer:
        def __init__(self, r):
            self.r = r

        def read(self):
            return self.r.content

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def urlopen(request, timeout):
        r = client.post("/mcp", content=request.data, headers=dict(request.header_items()))
        if r.status_code >= 400:
            raise urllib.error.HTTPError(request.full_url, r.status_code, "no", {}, __import__("io").BytesIO(r.content))
        return Answer(r)

    monkeypatch.setattr(mcp_bridge.urllib.request, "urlopen", urlopen)
    call = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                       "params": {"name": "probe_echo", "arguments": {"word": "hi"}}})
    answer = json.loads(mcp_bridge.relay(call, "http://127.0.0.1/mcp", token))
    assert answer["id"] == 7 and json.loads(answer["result"]["content"][0]["text"])["said"] == "hi"
    assert mcp_bridge.relay('{"jsonrpc": "2.0", "method": "notifications/initialized"}', "http://127.0.0.1/mcp", token) is None
    refused = json.loads(mcp_bridge.relay(call, "http://127.0.0.1/mcp", "wrong"))
    assert refused["id"] == 7 and "Settings → Claude" in refused["error"]["message"]


def test_the_bridge_says_when_the_app_isnt_running():
    env = {**os.environ, "MCP_TOKEN": "anything"}
    lines = '{"jsonrpc": "2.0", "id": 1, "method": "ping"}\n{"jsonrpc": "2.0", "method": "notifications/initialized"}\n'
    done = subprocess.run([sys.executable, "-B", str(mcp.BRIDGE), "http://127.0.0.1:9/mcp"], input=lines,
                          capture_output=True, text=True, env=env, timeout=30)
    assert done.returncode == 0
    [answer] = [json.loads(line) for line in done.stdout.splitlines()]
    assert answer == {"jsonrpc": "2.0", "id": 1, "error": {"code": -32001, "message": mcp_bridge.APP_DOWN}}
