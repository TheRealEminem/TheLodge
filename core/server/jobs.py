"""Background work that survives restarts.

A job is one step of work on one thing (module "notes", kind "summarize", target <note id>). Jobs run one at
a time on a single worker thread, so heavy steps (a local model, a big export) never compete for memory.
A kind can opt into the "cloud" lane (register(..., lane="cloud")): work that waits on a web API rather than
this machine's memory, so a few run side by side (a folder of 90 documents in minutes, not an hour). The
"interactive" lane is for work someone is sitting there waiting for (an answer to a question), so it never
queues behind a batch. The lane can also be chosen per job: lane=lambda target: "cloud" if the cloud is doing
it, else "default".

  queued -> running -> done
                    -> error    (POST /api/jobs/<id>/retry puts it back in the queue)
                    -> waiting  (the handler raised Wait: e.g. not enough free memory; "go" with force; a job
                                 waiting for memory goes again by itself once there's room: resume_when_room)
  waiting <- enqueue(..., approve=True): parked until you press the button ("Needs you"; POST /api/jobs/<id>/go)
  waiting -> queued by itself (release) when what it waited for has passed: Lockdown turned off (lockdown.py)

State lives in the database, so after a restart unfinished jobs simply run again: write handlers so that
running twice is harmless (check what's already done, then do the rest).
"""
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Callable

from . import db, events, resources

log = logging.getLogger("core.jobs")
UNFINISHED = ("queued", "running", "waiting")

LANES = {"default": 1, "cloud": 4, "interactive": 2}   # lane -> how many jobs run at once
_executors = {name: ThreadPoolExecutor(max_workers=n, thread_name_prefix=f"jobs-{name}") for name, n in LANES.items()}
_handlers: dict[tuple[str, str], tuple[Callable, "str | Callable[[str], str]"]] = {}
_pending: list[Future] = []
_pending_lock = threading.Lock()
_current: ContextVar["Job | None"] = ContextVar("job", default=None)


class Wait(Exception):
    """Raise from a handler to park the job, with a reason people can read. Unless the job was forced past it."""


@dataclass
class Job:
    id: str
    module: str
    kind: str
    target: str
    approved: bool
    forced: bool

    def stage(self, text: str) -> None:
        """Progress in words, shown next to the item while it runs."""
        _set(self.id, stage=text)


def register(module: str, kind: str, handler: Callable[[Job], None], lane: "str | Callable[[str], str]" = "default") -> None:
    """lane: "default" (one at a time), "cloud" (a few at once), "interactive" (someone is waiting for it), or a
    function of the target that returns one."""
    _handlers[(module, kind)] = (handler, lane)


def enqueue(module: str, kind: str, target: str, approve: bool = False, reason: str = "Needs you") -> str:
    """Queues the work, or parks it until approved (approve=True). An unfinished job of the same kind for the
    same target is reused rather than doubled; a waiting one that's now being started by hand goes ahead."""
    existing = db.one(
        f"SELECT id, status FROM core_jobs WHERE module = ? AND kind = ? AND target = ? AND status IN {UNFINISHED}",
        (module, kind, target),
    )
    if existing:
        if existing["status"] == "waiting" and not approve:
            go(existing["id"])
        return existing["id"]
    job_id = db.new_id()
    stamp = db.now()
    db.execute(
        "INSERT INTO core_jobs (id, module, kind, target, status, wait_reason, approved, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (job_id, module, kind, target, "waiting" if approve else "queued", reason if approve else None,
         int(not approve), stamp, stamp),
    )
    events.publish("core.job.changed", {"module": module, "target": target})
    if not approve:
        _submit(job_id)
    return job_id


def go(job_id: str, force: bool = False) -> None:
    """Starts a waiting job (you approved it, or chose to go ahead despite its warning)."""
    _yours_only("start work that waits for you")
    changed = db.execute(
        "UPDATE core_jobs SET status = 'queued', approved = 1, forced = forced OR ?, wait_reason = NULL, updated_at = ? "
        "WHERE id = ? AND status = 'waiting'",
        (int(force), db.now(), job_id),
    )
    if changed:
        _notify(job_id)
        _submit(job_id)


def resume_when_room() -> list[str]:
    """Puts back in the queue the jobs parked for lack of memory, once the local model has room. The scheduler calls this."""
    rows = db.query("SELECT id FROM core_jobs WHERE status = 'waiting' AND wait_reason LIKE ?", ("%" + resources.WAIT + "%",))
    if not rows:
        return []
    from . import ai                       # late: ai reads settings, which the jobs table doesn't need
    if not ai.memory_ready():
        return []
    for row in rows:
        go(row["id"])
    return [r["id"] for r in rows]


def retry(job_id: str) -> None:
    _yours_only("try failed work again")
    if db.execute("UPDATE core_jobs SET status = 'queued', error = NULL, updated_at = ? WHERE id = ? AND status = 'error'",
                  (db.now(), job_id)):
        _notify(job_id)
        _submit(job_id)


def release(job_id: str) -> None:
    """Starts a waiting job again because what it waited for has passed by itself (Lockdown turned off). Not an
    approval: only work that was already going parks that way, so Claude's tools don't stop it."""
    if db.execute("UPDATE core_jobs SET status = 'queued', wait_reason = NULL, updated_at = ? WHERE id = ? AND status = 'waiting'",
                  (db.now(), job_id)):
        _notify(job_id)
        _submit(job_id)


def _yours_only(what: str) -> None:
    """Approving is yours: Claude's tools (mcp.py) may queue work and park it for you, never start what waits."""
    from . import mcp   # here rather than at the top: mcp loads the modules, which load this
    if mcp.calling():
        raise PermissionError(f"Claude can't {what}. Only you can, in the app.")


def cancel_for(module: str, target: str) -> None:
    """Forgets unstarted work for something that's being deleted."""
    db.execute("DELETE FROM core_jobs WHERE module = ? AND target = ? AND status IN ('queued', 'waiting')", (module, target))


def latest(module: str, targets: list[str]) -> dict[str, dict]:
    """target -> its most recent job, in the shape the web app shows (see JobStatus in the web core)."""
    if not targets:
        return {}
    marks = ",".join("?" * len(targets))
    rows = db.query(
        f"SELECT id, kind, target, status, stage, wait_reason, error, updated_at FROM core_jobs "
        f"WHERE module = ? AND target IN ({marks}) ORDER BY created_at",
        (module, *targets),
    )
    return {r["target"]: r for r in rows}  # later rows win


def waiting(module: str, kind: str) -> list[str]:
    """Ids of this kind of job that are parked (for "resume everything")."""
    return [r["id"] for r in db.query("SELECT id FROM core_jobs WHERE module = ? AND kind = ? AND status = 'waiting' ORDER BY created_at",
                                      (module, kind))]


def current() -> Job | None:
    """The job this thread is running, if any (the AI usage log names the module and job that asked)."""
    return _current.get()


def busy() -> bool:
    return db.one("SELECT 1 AS x FROM core_jobs WHERE status IN ('queued', 'running')") is not None


def recover() -> None:
    """On startup: anything that was queued or cut off mid-run goes again."""
    db.execute("UPDATE core_jobs SET status = 'queued' WHERE status = 'running'")
    for row in db.query("SELECT id FROM core_jobs WHERE status = 'queued' ORDER BY created_at"):
        _submit(row["id"])


def drain(timeout: float = 30) -> None:
    """Tests: wait until everything submitted so far has run."""
    while True:
        with _pending_lock:
            if not _pending:
                return
            future = _pending.pop(0)
        future.result(timeout=timeout)


# ── Running ───────────────────────────────────────────────────────────

def _lane_of(job_id: str) -> str:
    row = db.one("SELECT module, kind, target FROM core_jobs WHERE id = ?", (job_id,))
    entry = _handlers.get((row["module"], row["kind"])) if row else None
    if not entry:
        return "default"
    lane = entry[1]
    try:
        lane = lane(row["target"]) if callable(lane) else lane
    except Exception:  # noqa: BLE001 - a lane that can't be worked out runs where it's safest
        log.exception("Couldn't choose a lane for job %s", job_id)
        lane = "default"
    return lane if lane in _executors else "default"


def _submit(job_id: str) -> None:
    future = _executors[_lane_of(job_id)].submit(_run, job_id)
    with _pending_lock:
        _pending.append(future)
        _pending[:] = [f for f in _pending if not f.done()]


def _set(job_id: str, **fields) -> None:
    fields["updated_at"] = db.now()
    db.execute(f"UPDATE core_jobs SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?", (*fields.values(), job_id))
    _notify(job_id)


def _notify(job_id: str) -> None:
    row = db.one("SELECT module, target FROM core_jobs WHERE id = ?", (job_id,))
    if row:
        events.publish("core.job.changed", row)


def _run(job_id: str) -> None:
    row = db.one("SELECT * FROM core_jobs WHERE id = ?", (job_id,))
    if not row or row["status"] != "queued":
        return
    handler = (_handlers.get((row["module"], row["kind"])) or (None,))[0]
    if not handler:
        _set(job_id, status="error", error=f"Nothing handles {row['module']}/{row['kind']} (is the module turned off?)")
        return
    job = Job(row["id"], row["module"], row["kind"], row["target"], bool(row["approved"]), bool(row["forced"]))
    _set(job_id, status="running", stage=None, error=None)
    running = _current.set(job)
    try:
        if job.forced:                      # "Proceed anyway": the memory gate stands aside for this one
            with resources.proceed_anyway():
                handler(job)
        else:
            handler(job)
    except Wait as why:
        _set(job_id, status="waiting", wait_reason=str(why), stage=None)
    except Exception as e:  # noqa: BLE001 - any failure is shown on the item, with Retry
        log.exception("Job %s/%s failed", row["module"], row["kind"])
        _set(job_id, status="error", error=str(e) or type(e).__name__, stage=None)
    else:
        _set(job_id, status="done", stage=None)
    finally:
        _current.reset(running)
