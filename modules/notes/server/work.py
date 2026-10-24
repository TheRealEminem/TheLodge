"""The notes module's background work."""
import re

from core.server import ai, contracts, events, links
from core.server.jobs import Job

from . import store

SYSTEM = """You write short, useful summaries of the user's notes.
Reply in Markdown: a one-paragraph overview, then "## Action items" with one "- [ ] …" line per thing someone
needs to do (or "- None"). Use only what the note says."""

_TASK = re.compile(r"^\s*[-*]\s*\[ \]\s*(.+?)\s*$", re.M)


def summarize(job: Job) -> None:
    note = store.get(job.target)
    if not note:
        return  # deleted meanwhile: nothing to do
    if not note["body"].strip():
        raise ValueError("The note is empty")
    job.stage("Summarizing")
    summary, provider = ai.complete(f"TITLE: {note['title']}\n\nNOTE:\n{note['body']}", system=SYSTEM, purpose="Note summaries")
    store.update(note["id"], summary=summary, summary_by=provider)
    items = [m.group(1) for m in _TASK.finditer(summary) if m.group(1).lower().rstrip(".") != "none"]
    events.publish("notes.note.summarized", {"id": note["id"]})
    events.publish(contracts.ACTIONS_FOUND, {"source_ref": links.ref("notes", note["id"]), "items": items})
