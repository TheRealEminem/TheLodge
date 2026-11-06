"""Claude Desktop starts the MCP servers it uses as commands that talk over stdin and stdout. This is that command for a
family app: it passes each message it reads on to the app's /mcp (mcp.py) and writes the answer back.

    <the app's Python> -B mcp_bridge.py http://127.0.0.1:<port>/mcp        with MCP_TOKEN=<token> in its environment

Settings → Claude writes that out, ready to paste. It uses Python's standard library only, so the Python inside the Mac
app runs it with nothing installed, and -B keeps it from writing anything next to itself (inside the app's bundle).
"""
import json
import os
import sys
import urllib.error
import urllib.request

APP_DOWN = "The app isn't running. Open it, then try again."


def relay(line: str, url: str, token: str, timeout: float = 120) -> str | None:
    """One message from Claude → the line to write back: the app's answer, or an error Claude can show (None when a
    notification needs no answer)."""
    try:
        message = json.loads(line)
    except ValueError:
        return json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "That isn't JSON."}})
    asked = message.get("id") if isinstance(message, dict) and "method" in message and "id" in message else None
    request = urllib.request.Request(url, data=line.encode(), method="POST", headers={
        "Content-Type": "application/json", "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode().strip() or None
    except urllib.error.HTTPError as e:
        try:
            problem = json.loads(e.read().decode())["error"]["message"]
        except (ValueError, KeyError, TypeError):
            problem = f"The app answered {e.code}."
    except (urllib.error.URLError, OSError):
        problem = APP_DOWN
    if asked is None:
        return None
    return json.dumps({"jsonrpc": "2.0", "id": asked, "error": {"code": -32001, "message": problem}})


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: mcp_bridge.py http://127.0.0.1:<port>/mcp (with MCP_TOKEN set)", file=sys.stderr)
        return 2
    url, token = sys.argv[1], os.environ.get("MCP_TOKEN", "")
    while line := sys.stdin.readline():
        if line.strip() and (answer := relay(line.strip(), url, token)):
            sys.stdout.write(answer + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
