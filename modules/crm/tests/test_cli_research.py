"""The Lodge researching people through an AI tool signed in on this Mac. A small program stands in for Claude Code,
Codex and Gemini CLI: these check how the tool is started (only the web, no API key), what it's given, what the Lodge
makes of its answer and its limits, not what the tool would find."""
import json
import os
import sys

import pytest
from crm_helpers import make

from core.server import db, jobs, settings
from modules.crm.server import cli_research as cr
from modules.crm.server import gemini_research as gr

# The stand-in: notes how it was started, then answers the way the tool named in its own file name would.
FAKE = r'''#!{python}
import json, os, pathlib, re, sys
here = pathlib.Path(__file__).parent
prompt = sys.stdin.read()
(here / "seen.json").write_text(json.dumps({"argv": sys.argv[1:], "env": sorted(os.environ), "prompt": prompt, "cwd": os.getcwd()}))
mode = (here / "mode").read_text().strip()
title = prompt.splitlines()[0]
ref = prompt.splitlines()[1]
report = f"I searched a few sources.\n\n# {title}\n{ref}\nIdentity confidence: High. Matched the employer.\n\nJordan Reyes runs fleet operations."
if mode == "limit":
    print(json.dumps({"is_error": True, "result": "You've hit your limit · resets 4pm"}))
elif mode == "broken":
    print("something went wrong", file=sys.stderr); sys.exit(3)
elif mode == "codex":
    out = pathlib.Path(sys.argv[sys.argv.index("-o") + 1])
    out.write_text(report)
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 900, "output_tokens": 400}}))
elif mode == "gemini":
    print(json.dumps({"response": report, "stats": {"models": {"gemini-3.8-flash": {"tokens": {"prompt": 700, "candidates": 300}}}}}))
else:
    print(json.dumps({"is_error": False, "result": report, "usage": {"input_tokens": 1200, "output_tokens": 500},
                      "modelUsage": {"claude-sonnet-5-5": {}}}))
'''


@pytest.fixture
def tool(tmp_path, monkeypatch, client):
    """A signed-in home for all three tools, the stand-in program found for each, and an API key in the environment
    that must not reach it."""
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".gemini").mkdir()
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {"emailAddress": "owner@example.org"}}))
    (home / ".codex" / "auth.json").write_text(json.dumps({"auth_mode": "chatgpt"}))
    (home / ".gemini" / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "oauth-personal"}}}))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-be-used")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    fake = bin_ / "tool"
    fake.write_text(FAKE.replace("{python}", sys.executable))
    fake.chmod(0o755)
    monkeypatch.setattr(cr, "find", lambda via: str(fake))
    client.put("/api/crm/me", json={"name": "Alex Rivera"})

    class Tool:
        def mode(self, m):
            (bin_ / "mode").write_text(m)

        def seen(self):
            return json.loads((bin_ / "seen.json").read_text())
    t = Tool()
    t.mode("claude")
    return t


def person(client, name="Jordan Reyes"):
    return make(client, "person", name, attributes={"title": "Head of Fleet", "email": "jordan@frostline.example"})


def run(client, pid):
    return client.get(f"/api/crm/people/{pid}/research/gemini").json()["run"]


def go(client, pid, via):
    r = client.post("/api/crm/research/gemini", json={"person_ids": [pid], "via": via})
    jobs.drain()
    return r


def test_claude_code_gets_the_brief_and_only_the_web_and_the_report_waits_in_the_inbox(client, tool):
    jordan = person(client)
    r = go(client, jordan["id"], "claude")
    assert r.status_code == 202 and r.json()["started"] == 1
    done = run(client, jordan["id"])
    assert done["status"] == "done" and done["via"] == "claude" and done["cost"] == 0
    seen = tool.seen()
    assert seen["argv"][seen["argv"].index("--tools") + 1] == "WebSearch,WebFetch" and "--strict-mcp-config" in seen["argv"]
    assert "ANTHROPIC_API_KEY" not in seen["env"]                                # its own sign-in, never a key that bills
    assert "frostline.example" in seen["prompt"] and "jordan@frostline.example" not in seen["prompt"]
    assert "Reply with only the finished report" in seen["prompt"]
    item = client.get(f"/api/crm/ingest/jobs/{done['inbox_id']}").json()
    assert item["payload"]["subject_id"] == jordan["id"]
    assert item["raw_text"].startswith("Jordan Reyes — research profile")        # what it said first is left out
    assert "with Claude Code, on your Claude plan" in item["raw_text"]
    use = db.one("SELECT * FROM core_ai_usage WHERE provider = 'claude' ORDER BY at DESC LIMIT 1")
    assert use["model"] == "claude-sonnet-5-5" and use["cost"] == 0 and use["tokens_in"] == 1200


@pytest.mark.parametrize("via, mode, flag", [("codex", "codex", "read-only"), ("gemini_cli", "gemini", "--skip-trust")])
def test_codex_and_gemini_cli_reports_are_read_from_where_each_puts_them(client, tool, via, mode, flag):
    tool.mode(mode)
    jordan = person(client)
    go(client, jordan["id"], via)
    done = run(client, jordan["id"])
    assert done["status"] == "done", done["error"]
    assert flag in tool.seen()["argv"]
    item = client.get(f"/api/crm/ingest/jobs/{done['inbox_id']}").json()
    assert "Lodge ref:" in item["raw_text"] and cr.TOOLS[via]["plan"] in item["raw_text"]


def test_a_plans_limit_waits_and_tries_again_later(client, tool):
    tool.mode("limit")
    jordan = person(client)
    go(client, jordan["id"], "claude")
    waiting = run(client, jordan["id"])
    assert waiting["status"] == "waiting" and "your Claude plan's limit" in waiting["error"]
    assert cr.seconds() == 60 and gr.seconds() == 0                               # Gemini's own job leaves it alone
    tool.mode("claude")
    jobs.enqueue("crm", "research_cli", "scheduled")
    jobs.drain()
    assert run(client, jordan["id"])["status"] == "waiting"                       # not before its wait is over
    db.execute("UPDATE crm_research_runs SET updated_at = '2000-01-01T00:00:00Z' WHERE entity_id = ?", (jordan["id"],))
    jobs.enqueue("crm", "research_cli", "scheduled")
    jobs.drain()
    assert run(client, jordan["id"])["status"] == "done"


def test_a_tool_that_fails_says_why_and_can_be_tried_again(client, tool):
    tool.mode("broken")
    jordan = person(client)
    go(client, jordan["id"], "codex")
    failed = run(client, jordan["id"])
    assert failed["status"] == "failed" and "something went wrong" in failed["error"]
    tool.mode("codex")
    assert client.post(f"/api/crm/research/gemini/{failed['id']}/retry").status_code == 202
    jobs.drain()
    assert run(client, jordan["id"])["status"] == "done"


def test_a_tool_on_an_api_key_or_not_signed_in_is_not_offered(client, tool, monkeypatch):
    home = cr.Path.home()
    (home / ".gemini" / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": "gemini-api-key"}}}))
    (home / ".claude.json").write_text("{}")
    tools = {t["id"]: t for t in client.get("/api/crm/research/gemini").json()["tools"]}
    assert tools["codex"]["ready"] and not tools["gemini_cli"]["ready"] and not tools["claude"]["ready"]
    assert "bills the key" in tools["gemini_cli"]["reason"] and "/login" in tools["claude"]["reason"]
    r = client.post("/api/crm/research/gemini", json={"person_ids": [person(client)["id"]], "via": "gemini_cli"})
    assert r.status_code == 422 and "Sign in with Google" in r.json()["detail"]
    monkeypatch.setattr(cr, "find", lambda via: None)
    assert "isn't installed" in cr.problem("codex")


def test_the_usual_way_comes_from_settings_and_a_run_already_going_is_skipped(client, tool):
    settings.update({"crm.research_via": "claude"})
    jordan = person(client)
    jordan_run = cr.start([jordan["id"]], "claude")
    assert jordan_run["started"] == 1
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]]}).json()
    assert r["started"] == 0 and "already being researched" in r["skipped"][0]["reason"]
    jobs.drain()
    settings.update({"crm.research_via": "api"})


def test_a_run_left_running_when_the_app_quit_starts_over(client, tool):
    jordan = person(client)
    now = db.now()
    db.execute("INSERT INTO crm_research_runs (id, entity_id, level, via, status, stage, created_at, updated_at) "
               "VALUES ('r1', ?, 'claude', 'claude', 'running', 'write', ?, ?)", (jordan["id"], now, now))
    jobs.enqueue("crm", "research_cli", "scheduled")
    jobs.drain()
    assert run(client, jordan["id"])["status"] == "done"


def test_parse_reads_each_tools_errors():
    assert cr.parse("claude", json.dumps({"is_error": True, "result": "Credit balance is too low"}), cr.Path("."))["error"] == "Credit balance is too low"
    assert "GEMINI_API_KEY" in cr.parse("gemini_cli", json.dumps({"error": {"message": "You must specify the GEMINI_API_KEY"}}), cr.Path("."))["error"]
    got = cr.parse("codex", json.dumps({"type": "turn.failed", "error": {"message": "usage limit reached"}}), cr.Path("/nonexistent"))
    assert got["error"] == "usage limit reached" and cr.LIMIT.search(got["error"])


def test_on_windows_the_tool_gets_what_it_needs_to_start_and_still_no_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "WINDOWS", True)
    monkeypatch.setenv("SYSTEMROOT", r"C:\\Windows")
    monkeypatch.setenv("COMSPEC", r"C:\\Windows\\System32\\cmd.exe")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-not-pass")
    env = cr.environment(str(tmp_path / "Roaming" / "npm" / "claude.cmd"))
    assert {"SYSTEMROOT", "COMSPEC", "APPDATA"} <= set(env)
    assert "ANTHROPIC_API_KEY" not in env and "HOME" not in env
    assert env["PATH"].split(os.pathsep)[0] == str(tmp_path / "Roaming" / "npm")


def test_stopping_a_run_ends_what_the_tool_started_too():
    import subprocess
    parent = subprocess.Popen([sys.executable, "-c", "import subprocess, sys, time; "
                               "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); time.sleep(60)"])
    try:
        for _ in range(50):
            kids = cr.psutil.Process(parent.pid).children(recursive=True)
            if kids:
                break
            __import__("time").sleep(0.1)
        assert kids
        cr._kill(parent)
        parent.wait(5)
        gone, alive = cr.psutil.wait_procs(kids, timeout=5)
        assert not alive
    finally:
        if parent.poll() is None:
            parent.kill()
