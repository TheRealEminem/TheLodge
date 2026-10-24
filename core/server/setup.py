"""The first run, and choosing where AI runs. The setup screen asks three things (where should AI run, is this Mac locked
down, anything a module wants to ask), and this is what it reads and writes.

The recommendation comes from resources.device_advice(): "local" when this Mac has room for everything an app asks of AI,
"mixed" when the light jobs fit but the heavy ones do better in the cloud, "cloud" when it's short of memory or disk.
Modules say how heavy their AI jobs are (Module.ai_jobs) so the host can place them without knowing what they do.

New or existing: the first time an app starts with this code it records whether it already had settings of its own. One that
did is an existing install and never sees the first-run screens; it gets a card in Settings → AI instead, until it chooses.
"""
from . import ai, module, resources, settings

DONE = "core.setup_done"


def mark_existing() -> None:
    """Called at startup. Records, once, whether this app had been used before this version (any saved setting)."""
    stored = settings.stored_here()
    if DONE not in stored:
        settings.update({DONE: bool(stored)})


def done() -> bool:
    return bool(settings.get_all().get(DONE))


def finish() -> None:
    settings.update({DONE: True})


def reopen() -> None:
    """Settings → App → Run setup again: show the first-run screens once more. Only the flag changes; nothing is deleted
    and every screen starts from what is already chosen."""
    settings.update({DONE: False})


def jobs() -> list[dict]:
    """Every module's AI jobs and where each would run now: [{module, job, label, hint, weight, provider, label_of_provider,
    model, ready, reason, local}]."""
    out = []
    for m in module.all_modules():
        for job, info in m.ai_jobs.items():
            weight = info.get("weight", "light")
            choice = (info["choice"]() if callable(info.get("choice")) else "auto")
            if choice == "rules":
                d = {"provider": "rules", "label": "Rules (no AI)", "model": "", "ready": True, "reason": "", "local": True}
            else:
                d = ai.describe(ai.resolve(choice, weight))
            out.append({"module": m.id, "job": job, "label": info["label"], "hint": info.get("hint", ""), "weight": weight,
                        "provider": d["provider"], "provider_label": d["label"], "model": d["model"], "ready": d["ready"],
                        "reason": d["reason"], "local": d["local"]})
    return out


def state() -> dict:
    advice = resources.device_advice()
    return {"done": done(), "path": settings.get_all().get("ai.path", ""), "recommended": advice["verdict"],
            "snapshot": resources.snapshot(), "advice": advice, "jobs": jobs(), "providers": ai.providers()}


def choose(path: str, cloud: str = "") -> dict:
    ai.apply_path(path, cloud)
    return state()
