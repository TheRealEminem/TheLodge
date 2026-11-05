"""The Lodge researching a person through an AI tool you're signed in to on this Mac: Claude Code, Codex or Gemini CLI,
on your own Claude, ChatGPT or Google plan instead of an API key.

A run hands the tool the research brief (research.brief, the one you'd paste into Deep Research), lets it search the
web as long as it needs, and files the report it writes in the Inbox like one you pasted, waiting for your OK. People
go one at a time. Nothing is charged here: a run counts against the plan's own limits, and when the tool says a limit
is reached the run waits and tries again later.

The tool gets nothing but the web. Claude Code has only WebSearch and WebFetch; Codex runs in its read-only sandbox with
live web search; Gemini CLI runs headless in its default mode, which refuses anything that writes or runs a command.
Each runs in an empty folder of its own, without your MCP servers, and with no API key in its environment, so it uses
the tool's own sign-in (an ANTHROPIC_API_KEY left in the environment would otherwise be billed instead).

    crm_research_runs   via = claude | codex | gemini_cli (gemini_research.py's own runs are via = api)
"""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import psutil

from core.server import computer, db, events, jobs, lockdown, settings
from core.server import usage as tally

from . import ingest, research

log = logging.getLogger("crm.cli_research")

TOOLS = {
    "claude": {"label": "Claude Code", "plan": "your Claude plan", "bin": "claude",
               "hint": "Claude Code searches the web and writes the report, on your Claude plan. Usually the most thorough."},
    "codex": {"label": "Codex", "plan": "your ChatGPT plan", "bin": "codex",
              "hint": "OpenAI's Codex searches the web and writes the report, on your ChatGPT plan."},
    "gemini_cli": {"label": "Gemini CLI", "plan": "your Google AI plan", "bin": "gemini",
                   "hint": "Gemini CLI searches Google and writes the report, on your Google AI plan."},
}
# Where these get installed. An app opened from the Finder or a desktop launcher has a short PATH, so it looks here too.
WINDOWS = sys.platform == "win32"
if WINDOWS:   # npm's global .cmd shims, Claude Code's own installer, Bun, pnpm, Volta, Scoop
    PLACES = ["%APPDATA%/npm", "~/.local/bin", "~/.claude/local", "~/.bun/bin", "%LOCALAPPDATA%/pnpm",
              "%LOCALAPPDATA%/Volta/bin", "~/scoop/shims"]
else:
    PLACES = ["/opt/homebrew/bin", "/usr/local/bin", "~/.local/bin", "~/.claude/local", "~/.npm-global/bin", "~/.bun/bin",
              "~/.volta/bin", "~/.local/share/pnpm", "/home/linuxbrew/.linuxbrew/bin"]
# What Windows programs need to start at all (Node won't run without SystemRoot; npm's .cmd shims need ComSpec), and
# where their sign-ins are. Still no API keys.
WINDOWS_ENV = ("SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA",
               "PROGRAMFILES", "TEMP", "TMP", "USERNAME", "HOMEDRIVE", "HOMEPATH", "CODEX_HOME")
RETRY_AFTER = 15 * 60      # seconds a run waits after the plan's limit is reached
UNFINISHED = ("queued", "running", "waiting")
LIMIT = re.compile(r"usage limit|rate.?limit|limit (?:reached|exceeded)|hit your limit|quota|too many requests|\b429\b|"
                   r"resets? (?:at|in)|try again (?:later|in)", re.I)

# How hard a run works: what it's told, how long its report is, the model and effort each tool is started with
# (Gemini CLI has no effort setting, so only what it's told changes), and how long it may take.
DEPTHS = {
    "light": {"label": "Light", "words": "600 to 900", "minutes": 15,
              "hint": "A quick look: who they are and the main facts, in about 10 searches. Uses the least of your plan.",
              "how": "This is a light pass: about 5 to 10 searches, enough to be sure who they are and find the main facts.",
              "claude": ["--model", "sonnet", "--effort", "low"], "codex": ["-c", 'model_reasoning_effort="low"']},
    "standard": {"label": "Standard", "words": "1,500 to 2,500", "minutes": 30,
                 "hint": "A full report with a source for every claim that matters, on the tool's usual model.",
                 "how": "Search the web as much as you need (dozens of searches is fine) and read the pages that matter.",
                 "claude": [], "codex": []},
    "deep": {"label": "Deep", "words": "3,000 to 5,000", "minutes": 60,
             "hint": "Exhaustive, on the strongest model: primary sources, every lead followed, claims checked twice. "
                     "Uses several times what a standard run does.",
             "how": "This is a deep session, so be thorough: run 40 or more searches, read primary sources (their own "
                    "sites, filings, talks, interviews, papers), follow every lead in the earlier search, and check "
                    "each important claim against a second source.",
             "claude": ["--model", "opus", "--effort", "high"], "codex": ["-c", 'model_reasoning_effort="high"']},
}


def instructions(depth: str) -> str:
    return ("You're running unattended for the owner of a personal CRM, with nobody to answer questions. "
            f"{DEPTHS[depth]['how']} Don't create or change any files. Reply with only the finished report in "
            "Markdown: no preamble, no questions, nothing after it.")


def night_hours() -> tuple[int, int]:
    """When overnight runs may go: from this hour up to (not including) that one, in this computer's time."""
    cfg = settings.section("crm")
    return int(cfg["research_night_from"]) % 24, int(cfg["research_night_to"]) % 24


def is_night(hour: int | None = None) -> bool:
    start, end = night_hours()
    h = datetime.now().hour if hour is None else hour
    if start == end:
        return True
    return start <= h < end if start < end else (h >= start or h < end)

_running: dict[str, subprocess.Popen] = {}
_lock = threading.Lock()


class CliResearchError(ValueError):
    pass


def _now() -> str:
    return db.now()


def _changed(person_id: str | None = None) -> None:
    events.publish("crm.research.changed", {"id": person_id})


def locked() -> str | None:
    return lockdown.blocked("Research through an AI tool")


# ── The tools on this Mac ─────────────────────────────────────────────

def _places() -> list[str]:
    return [os.path.expandvars(os.path.expanduser(p)) for p in PLACES]


def find(via: str) -> str | None:
    """Where the tool's program is, or None when it isn't installed."""
    places = [*os.environ.get("PATH", "").split(os.pathsep), *_places()]
    return shutil.which(TOOLS[via]["bin"], path=os.pathsep.join(p for p in places if p))


def _terminal() -> str:
    return computer.word("terminal")


def _json_file(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def sign_in_problem(via: str) -> str | None:
    """Why the tool wouldn't run on a plan's sign-in, in words for a person, or None when it's signed in. Only the
    marker of how it's signed in is read, never a token."""
    home = Path.home()
    if via == "claude":
        if _json_file(home / ".claude.json").get("oauthAccount"):
            return None
        return f"Claude Code isn't signed in to a Claude account. In {_terminal()}, run claude and type /login."
    if via == "codex":
        mode = _json_file(Path(os.environ.get("CODEX_HOME") or home / ".codex") / "auth.json").get("auth_mode")
        if mode == "chatgpt":
            return None
        if mode:
            return f"Codex is signed in with an API key, which bills the key. In {_terminal()}, run codex login and sign in with ChatGPT."
        return f"Codex isn't signed in. In {_terminal()}, run codex login and sign in with ChatGPT."
    cfg = _json_file(home / ".gemini" / "settings.json")
    mode = ((cfg.get("security") or {}).get("auth") or {}).get("selectedType") or cfg.get("selectedType")
    if mode == "oauth-personal":
        return None
    if mode:
        return ("Gemini CLI is set to use an API key, which bills the key instead of your Google plan. "
                f"In {_terminal()}, "
                "run gemini, type /auth and choose Sign in with Google.")
    return f"Gemini CLI isn't signed in. In {_terminal()}, run gemini and choose Sign in with Google."


def problem(via: str) -> str | None:
    """Why research can't go through this tool now, or None when it can."""
    if via not in TOOLS:
        return "Unknown research tool"
    if (why := locked()):
        return why
    if not find(via):
        return f"{TOOLS[via]['label']} isn't installed on {computer.word('here')}."
    return sign_in_problem(via)


def tools() -> list[dict]:
    """For the start dialog and Settings: each tool, and whether it's ready."""
    return [{"id": k, "label": t["label"], "plan": t["plan"], "hint": t["hint"], "ready": not (why := problem(k)),
             "reason": why} for k, t in TOOLS.items()]


def depths() -> list[dict]:
    return [{"id": k, "label": d["label"], "hint": d["hint"]} for k, d in DEPTHS.items()]


# ── One run ───────────────────────────────────────────────────────────

def command(via: str, program: str, folder: Path, depth: str = "standard") -> list[str]:
    if via == "claude":
        return [program, "-p", "--output-format", "json", "--tools", "WebSearch,WebFetch", "--allowedTools", "WebSearch",
                "WebFetch", "--permission-mode", "dontAsk", "--strict-mcp-config", "--no-session-persistence",
                *DEPTHS[depth]["claude"]]
    if via == "codex":
        return [program, "exec", "-c", 'web_search="live"', "-c", "mcp_servers={}", *DEPTHS[depth]["codex"],
                "--skip-git-repo-check", "--ephemeral", "-s", "read-only", "--color", "never", "-C", str(folder),
                "-o", str(folder / "report.md"), "--json", "-"]
    return [program, "-o", "json", "--skip-trust", "-e", "none", "-p", "Write the report now."]


def environment(program: str) -> dict:
    """Just enough to find the tool and its sign-in: no API keys, so it can't bill one."""
    if WINDOWS:
        system = os.environ.get("SYSTEMROOT", r"C:\Windows")
        path = [str(Path(program).parent), *_places(), os.path.join(system, "System32"), system]
        env = {"PATH": os.pathsep.join(dict.fromkeys(path)), "NO_COLOR": "1"}
        keep = WINDOWS_ENV
    else:
        path = [str(Path(program).parent), *_places(), "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
        env = {"HOME": str(Path.home()), "PATH": os.pathsep.join(dict.fromkeys(path)), "LANG": "en_US.UTF-8",
               "TERM": "dumb", "NO_COLOR": "1"}
        keep = ("USER", "LOGNAME", "TMPDIR", "CODEX_HOME")
    for k in keep:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def parse(via: str, out: str, folder: Path) -> dict:
    """{text, error, model, in, out} from what the tool printed (and, for Codex, the report file it wrote)."""
    got = {"text": "", "error": None, "model": TOOLS[via]["label"], "in": 0, "out": 0}
    if via == "codex":
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if ev.get("type") in ("error", "turn.failed"):
                got["error"] = str((ev.get("error") or {}).get("message") or ev.get("message") or "Codex stopped")
            if ev.get("type") == "turn.completed":
                u = ev.get("usage") or {}
                got["in"] += int(u.get("input_tokens") or 0)
                got["out"] += int(u.get("output_tokens") or 0) + int(u.get("reasoning_output_tokens") or 0)
        try:
            got["text"] = (folder / "report.md").read_text().strip()
        except OSError:
            pass
        return got
    try:
        data = json.loads(out[out.find("{"):]) if "{" in out else {}
    except ValueError:
        data = {}
    if via == "claude":
        if data.get("is_error"):
            got["error"] = str(data.get("result") or data.get("terminal_reason") or "Claude Code stopped")
        else:
            got["text"] = str(data.get("result") or "").strip()
        u = data.get("usage") or {}
        got["in"] = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        got["out"] = int(u.get("output_tokens") or 0)
        got["model"] = next(iter(data.get("modelUsage") or {}), got["model"])
        return got
    if data.get("error"):
        got["error"] = str((data["error"] or {}).get("message") or "Gemini CLI stopped")
    got["text"] = str(data.get("response") or "").strip()
    for name, m in ((data.get("stats") or {}).get("models") or {}).items():
        t = m.get("tokens") or {}
        got["model"], got["in"], got["out"] = name, got["in"] + int(t.get("prompt") or 0), got["out"] + int(t.get("candidates") or 0)
    return got


def trim(text: str, title: str) -> str:
    """The report from its title on: tools sometimes say a line about what they did first."""
    at = text.find(title)
    return text[at:].lstrip("# ").strip() if at > 0 else text.strip()


def _stay_awake(pid: int) -> None:
    """Keeps a Mac from dozing off while the tool works (an overnight run especially). Ends with the tool."""
    if sys.platform == "darwin" and (caffeinate := shutil.which("caffeinate", path="/usr/bin")):
        subprocess.Popen([caffeinate, "-i", "-w", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def research_one(via: str, run_id: str, prompt: str, depth: str = "standard") -> dict:
    """Runs the tool on one brief and waits for it. {text, error, limited, model, in, out}."""
    timeout = DEPTHS[depth]["minutes"] * 60
    program = find(via)
    if not program:
        return {"text": "", "error": f"{TOOLS[via]['label']} isn't installed on {computer.word('here')}.", "limited": False}
    with tempfile.TemporaryDirectory(prefix="lodge-research-") as tmp:
        folder = Path(tmp)
        try:
            proc = subprocess.Popen(command(via, program, folder, depth), cwd=folder, env=environment(program),
                                    encoding="utf-8", errors="replace", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as e:
            return {"text": "", "error": f"Couldn't start {TOOLS[via]['label']}: {e}", "limited": False}
        with _lock:
            _running[run_id] = proc
        _stay_awake(proc.pid)
        try:
            out, err = proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill(proc)
            proc.communicate()
            return {"text": "", "error": f"{TOOLS[via]['label']} took longer than {timeout // 60} minutes", "limited": False}
        finally:
            with _lock:
                _running.pop(run_id, None)
        got = parse(via, out, folder)
    if not got["text"] and not got["error"]:
        tail = (err or out).strip().splitlines()[-1:] or [f"it ended with code {proc.returncode}"]
        got["error"] = f"{TOOLS[via]['label']} wrote nothing: {tail[0][:300]}"
    got["limited"] = bool(got["error"] and LIMIT.search(got["error"] + " " + (err or "")[-500:]))
    return got


def stop(run_id: str) -> None:
    """Ends the tool's work on a run being cancelled."""
    with _lock:
        proc = _running.get(run_id)
    if proc and proc.poll() is None:
        _kill(proc)


def _kill(proc: subprocess.Popen) -> None:
    """Ends the tool and whatever it started. On Windows the program is often an npm .cmd shim, and killing only the
    shim would leave Node running the research."""
    try:
        children = psutil.Process(proc.pid).children(recursive=True)
    except psutil.Error:
        children = []
    for child in children:
        try:
            child.kill()
        except psutil.Error:
            pass
    proc.kill()


# ── Runs ──────────────────────────────────────────────────────────────

def _update(run_id: str, **fields) -> None:
    fields["updated_at"] = _now()
    db.execute(f"UPDATE crm_research_runs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), run_id))


def start(person_ids: list[str], via: str, depth: str = "standard", night: bool = False) -> dict:
    """Queue research on these people through this tool, at this depth. Overnight, a run waits for the night hours
    (night_hours) before it starts. Someone already being researched, or who can't be (no surname), is skipped and
    said why."""
    if (why := problem(via)):
        raise CliResearchError(why)
    if depth not in DEPTHS:
        raise CliResearchError("Unknown depth")
    started, skipped = [], []
    for pid in dict.fromkeys(person_ids):
        try:
            sub = research.subject(pid)
        except research.ResearchError as e:
            skipped.append({"id": pid, "reason": str(e)})
            continue
        if db.one(f"SELECT 1 AS x FROM crm_research_runs WHERE entity_id = ? AND status IN {UNFINISHED}", (pid,)):
            skipped.append({"id": pid, "reason": f"{sub.person.name} is already being researched"})
            continue
        now = _now()
        db.execute("INSERT INTO crm_research_runs (id, entity_id, level, via, batch, status, stage, depth, night, created_at, "
                   "updated_at) VALUES (?, ?, ?, ?, 0, 'queued', 'write', ?, ?, ?, ?)", (db.new_id(), pid, via, via, depth, int(night), now, now))
        started.append(pid)
    if started:
        jobs.enqueue("crm", "research_cli", "scheduled")
        _changed()
    return {"started": len(started), "skipped": skipped, "estimate_each": 0}


def _due() -> dict | None:
    """The next run to work on: queued ones first, then any whose wait for the plan's limit is over. Overnight runs
    only during the night hours; one already going when they end finishes."""
    since = db.one("SELECT strftime('%Y-%m-%dT%H:%M:%fZ', 'now', ?) AS t", (f"-{RETRY_AFTER} seconds",))["t"]
    return db.one("SELECT * FROM crm_research_runs WHERE via != 'api' AND (status = 'queued' OR (status = 'waiting' "
                  f"AND updated_at <= ?)) {'' if is_night() else 'AND night = 0 '}"
                  "ORDER BY status = 'waiting', created_at LIMIT 1", (since,))


def handle(job: jobs.Job) -> None:
    """Works through the queue one person at a time. Only one of these runs at once (the job is shared), so a run
    still marked running is one an earlier session left when the app quit: it goes back in the queue."""
    if locked():
        return
    db.execute("UPDATE crm_research_runs SET status = 'queued' WHERE via != 'api' AND status = 'running'")
    while (r := _due()) is not None:
        _run(job, r)


def _run(job: jobs.Job, r: dict) -> None:
    via, label = r["via"], TOOLS.get(r["via"], {}).get("label", r["via"])
    if (why := problem(via)):
        _update(r["id"], status="failed", error=why, finished_at=_now())
        _changed(r["entity_id"])
        return
    try:
        sub = research.subject(r["entity_id"])
        depth = r["depth"] if r["depth"] in DEPTHS else "standard"
        prompt = f"{research.brief(r['entity_id'], DEPTHS[depth]['words'])}\n\n---\n\n{instructions(depth)}"
    except research.ResearchError as e:
        _update(r["id"], status="failed", error=str(e), finished_at=_now())
        _changed(r["entity_id"])
        return
    _update(r["id"], status="running", error=None)
    _changed(r["entity_id"])
    job.stage(f"{label} is researching {sub.person.name} ({DEPTHS[depth]['label'].lower()})")
    got = research_one(via, r["id"], prompt, depth)
    if (db.one("SELECT status FROM crm_research_runs WHERE id = ?", (r["id"],)) or {}).get("status") != "running":
        return                                                      # cancelled while the tool worked
    tally.record(via, got.get("model") or label, got.get("in", 0), got.get("out", 0), cost=0.0, source="Researching people")
    if got["text"]:
        report = trim(got["text"], sub.title)
        footer = (f"\n\n---\nResearched by The Lodge with {label} ({DEPTHS[depth]['label'].lower()}), on "
                  f"{TOOLS[via]['plan']}, on {sub.today}.")
        row = ingest.create_note_job(report + footer, sub.title, None, r["entity_id"],
                                     auto_apply=settings.section("crm")["research_auto_add"])
        _update(r["id"], status="done", stage="done", inbox_id=row["id"], finished_at=_now())
    elif got["limited"]:
        _update(r["id"], status="waiting", error=f"Waiting for {TOOLS[via]['plan']}'s limit: {got['error'][:200]}. "
                                                 f"Trying again in {RETRY_AFTER // 60} minutes.")
    else:
        _update(r["id"], status="failed", error=got["error"], finished_at=_now())
    _changed(r["entity_id"])


def retry(run_id: str) -> None:
    _update(run_id, status="queued", error=None, finished_at=None)
    jobs.enqueue("crm", "research_cli", "scheduled")


def seconds() -> int:
    """Every minute while a run is queued or waiting on a limit or the night, otherwise not at all."""
    if locked():
        return 0
    return 60 if db.one("SELECT 1 AS x FROM crm_research_runs WHERE via != 'api' AND status IN ('queued', 'waiting')") else 0
