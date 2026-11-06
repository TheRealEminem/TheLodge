"""The MCP server: Claude Code, Claude Desktop and other MCP clients use the app through tools its modules offer.

Each module may list tools (Module.tools, a list of Tool): what Claude may ask of it, with a JSON Schema for the
arguments and a handler that gets them as a dict and returns plain data, or raises ValueError with a sentence a person
can read. Claude sees each as "<module>_<name>", named after the module that owns it (ARCHITECTURE.md §3, rule 2). A
tool calls its own module's code, which reaches the rest of the app through the host as always; modules still never
import each other.

The transport is MCP's streamable HTTP at /mcp, in its plainest form: each POST carries one JSON-RPC message (or a
batch) and gets its answer back as JSON. There are no sessions and no stream from the server (GET is 405), which the
protocol allows. Claude Desktop starts its servers as commands instead, so it runs mcp_bridge.py, which passes each
message on to /mcp.

What keeps it safe:
- **A token.** Claude's access is off until you make one in Settings → Claude. It's kept as core.mcp_token, write-only
  like every secret: the page sees it once, in the commands to copy, and then only its last four characters. Every
  request carries it as "Authorization: Bearer <token>".
- **Not from web pages.** A request with an Origin other than this Mac's is refused, so a site in a browser can't reach
  the app through localhost.
- **Tools work for you, never as you.** While a tool runs, nothing that waits for your approval can be started:
  jobs.go and jobs.retry refuse, and `calling()` lets a module refuse anything else (the plane module's client won't
  write). So a tool can add things here and propose things, but whatever needs your yes still waits for it in the app.
"""
import asyncio
import hmac
import json
import logging
import secrets
import sys
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response

from . import config, events, module, settings

log = logging.getLogger("core.mcp")

TOKEN_KEY = "core.mcp_token"
PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")   # newest first
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
BRIDGE = Path(__file__).with_name("mcp_bridge.py")
_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
_calling: ContextVar[str | None] = ContextVar("mcp_calling", default=None)


@dataclass
class Tool:
    """Something Claude may do in a module (Module.tools)."""
    name: str                                  # Claude sees "<module id>_<name>"
    title: str                                 # for people: "What's on my plate"
    description: str                           # for Claude: what it does, when to use it, and what it never does
    handler: Callable[[dict], Any]             # (arguments) -> plain data; raise ValueError("A sentence.") to refuse
    params: dict = field(default_factory=dict)            # the arguments' JSON Schema properties
    required: tuple[str, ...] = ()
    writes: bool = False                       # adds or changes something in this app (never anywhere else)


class _RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def declare() -> None:
    settings.declare("core", {"mcp_token": ""})


def calling() -> str | None:
    """The tool being called in this thread, or None. Code that only you may run checks it and refuses."""
    return _calling.get()


def url() -> str:
    return f"http://127.0.0.1:{config.PORT}/mcp"


def tools() -> list[tuple[str, module.Module, Tool]]:
    """Every active module's tools, as (the name Claude sees, the module, the tool)."""
    return [(f"{m.id}_{t.name}", m, t) for m in module.active_modules() for t in m.tools]


# ── The protocol (JSON-RPC 2.0) ───────────────────────────────────────

def handle(message: Any) -> dict | None:
    """One JSON-RPC message → its answer, or None for a notification (or a response: this server never asks)."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _error(None, -32600, "That isn't a JSON-RPC 2.0 message.")
    if "method" not in message:
        return None
    rid, method = message.get("id"), message["method"]
    params = message.get("params") or {}
    try:
        if not isinstance(params, dict):
            raise _RpcError(-32602, "params must be an object.")
        if method == "initialize":
            result = _initialize(params)
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": [_listed(name, m, t) for name, m, t in tools()]}
        elif method == "tools/call":
            result = call_tool(params.get("name"), params.get("arguments") or {})
        elif "id" not in message:
            return None                        # notifications/initialized, notifications/cancelled…
        else:
            raise _RpcError(-32601, f"{config.NAME} doesn't do {method}.")
    except _RpcError as e:
        return None if "id" not in message else _error(rid, e.code, str(e))
    return None if "id" not in message else {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _initialize(params: dict) -> dict:
    asked = params.get("protocolVersion")
    return {
        "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
        "capabilities": {"tools": {"listChanged": False}},
        "serverInfo": {"name": config.APP_ID, "title": config.NAME, "version": config.VERSION},
        "instructions": instructions(),
    }


def instructions() -> str:
    you = settings.section("core")["your_name"].strip() or "the user"
    today = date.today()
    return (f"{config.NAME} is {you}'s own app on this Mac ({config.IDENTITY.get('tagline', '')}). Its tools read what "
            f"it keeps and add to it. They never send anything anywhere else and never approve anything: whatever "
            f"waits for approval waits for {you} in the app. Today is {today:%A} {today.isoformat()}. Things come "
            f"with an href; they open at http://127.0.0.1:{config.PORT}/<href>.")


def _listed(name: str, owner: module.Module, tool: Tool) -> dict:
    return {
        "name": name, "title": tool.title, "description": tool.description,
        "inputSchema": {"type": "object", "properties": tool.params, "required": list(tool.required),
                        "additionalProperties": False},
        "annotations": {"title": tool.title, "readOnlyHint": not tool.writes, "destructiveHint": False,
                        "idempotentHint": not tool.writes, "openWorldHint": False},
    }


def call_tool(name: Any, arguments: Any) -> dict:
    found = next(((m, t) for n, m, t in tools() if n == name), None)
    if found is None:
        raise _RpcError(-32602, f"{config.NAME} has no tool called {name}.")
    owner, tool = found
    try:
        _check(tool, arguments)
        token = _calling.set(name)
        try:
            data = tool.handler(arguments)
        finally:
            _calling.reset(token)
    except (ValueError, PermissionError) as e:
        log.info("Claude used %s: refused (%s)", name, e)
        return _content(str(e), error=True)
    except Exception:  # noqa: BLE001 - Claude gets a sentence; the details go to the log
        log.exception("Claude used %s: it failed", name)
        return _content(f"Something went wrong in {owner.name}. The details are in {config.NAME}'s log.", error=True)
    log.info("Claude used %s", name)
    return _content(data)


def _check(tool: Tool, arguments: Any) -> None:
    """The arguments against the tool's schema, one level deep: the handler checks the values themselves."""
    if not isinstance(arguments, dict):
        raise ValueError("The arguments must be an object.")
    missing = [k for k in tool.required if arguments.get(k) in (None, "")]
    if missing:
        raise ValueError(f"Missing: {' and '.join(missing)}.")
    for key, value in arguments.items():
        spec = tool.params.get(key)
        if spec is None:
            raise ValueError(f"{key} isn't something this tool takes. It takes {', '.join(tool.params) or 'nothing'}.")
        if value is None:
            continue
        kind = _TYPES.get(spec.get("type"))
        if kind and (not isinstance(value, kind) or (isinstance(value, bool) and spec["type"] != "boolean")):
            raise ValueError(f"{key} must be a{'n' if spec['type'][0] in 'aeiou' else ''} {spec['type']}.")
        if "enum" in spec and value not in spec["enum"]:
            raise ValueError(f"{key} must be one of {', '.join(map(str, spec['enum']))}.")


def _content(data: Any, error: bool = False) -> dict:
    text = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, indent=1, default=str)
    return {"content": [{"type": "text", "text": text}], "isError": error}


# ── The endpoint ──────────────────────────────────────────────────────

router = APIRouter()


def _refused(status: int, message: str) -> JSONResponse:
    return JSONResponse(_error(None, -32001, message), status_code=status)


async def _refusal(request: Request) -> JSONResponse | None:
    origin = request.headers.get("origin")
    if origin and urlparse(origin).hostname not in LOCAL_HOSTS | {request.url.hostname}:
        return _refused(403, f"{config.NAME} doesn't answer MCP requests from web pages.")
    stored = settings.get_all().get(TOKEN_KEY) or ""
    if not stored:
        return _refused(403, f"Claude's access to {config.NAME} is off. Turn it on in {config.NAME}'s Settings → Claude.")
    given = request.headers.get("authorization", "")
    if not (given.startswith("Bearer ") and hmac.compare_digest(given[7:].strip().encode(), stored.encode())):
        await asyncio.sleep(0.5)               # slow down guessing
        return _refused(401, f"That token isn't {config.NAME}'s, or it's been replaced. "
                             f"Copy the command in {config.NAME}'s Settings → Claude again.")
    return None


@router.post("/mcp")
async def mcp_post(request: Request):
    refusal = await _refusal(request)
    if refusal:
        return refusal
    version = request.headers.get("mcp-protocol-version")
    if version and version not in PROTOCOL_VERSIONS:
        return JSONResponse(_error(None, -32600, f"{config.NAME} doesn't speak MCP {version}."), status_code=400)
    try:
        body = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_error(None, -32700, "That isn't JSON."), status_code=400)
    if isinstance(body, list):
        if not body:
            return JSONResponse(_error(None, -32600, "An empty batch."), status_code=400)
        answers = [a for a in [await run_in_threadpool(handle, m) for m in body] if a is not None]
        return JSONResponse(answers) if answers else Response(status_code=202)
    answer = await run_in_threadpool(handle, body)
    return JSONResponse(answer) if answer is not None else Response(status_code=202)


@router.get("/mcp")
@router.delete("/mcp")
def mcp_other():
    """No stream from the server and no sessions to end: every answer comes back with its request."""
    return Response(status_code=405, headers={"Allow": "POST"})


# ── Settings → Claude (behind the app's sign-in, like the rest of /api) ──

api_router = APIRouter()


def status() -> dict:
    hint = settings.public()["secret_hints"].get(TOKEN_KEY)
    return {"on": bool(hint), "hint": hint, "url": url(),
            "tools": [{"name": name, "title": t.title, "module": m.name, "writes": t.writes} for name, m, t in tools()]}


def setup(token: str) -> dict:
    """What to paste where: a command for Claude Code, and the config for Claude Desktop, which runs the bridge with
    this app's own Python."""
    desktop = {"mcpServers": {config.APP_ID: {"command": sys.executable, "args": ["-B", str(BRIDGE), url()],
                                              "env": {"MCP_TOKEN": token}}}}
    return {"claude_code": f'claude mcp add --scope user --transport http {config.APP_ID} {url()} '
                           f'--header "Authorization: Bearer {token}"',
            "claude_desktop": json.dumps(desktop, indent=2)}


@api_router.get("/mcp")
def mcp_status():
    return status()


@api_router.post("/mcp/token")
def make_token():
    """A new token (the old one stops working), shown this once inside the commands to copy."""
    token = secrets.token_urlsafe(32)
    settings.update({TOKEN_KEY: token})
    events.publish("core.settings.changed", {"keys": [TOKEN_KEY]})
    return {**status(), "setup": setup(token)}


@api_router.delete("/mcp/token", status_code=204)
def turn_off():
    settings.update({TOKEN_KEY: ""})
    events.publish("core.settings.changed", {"keys": [TOKEN_KEY]})
