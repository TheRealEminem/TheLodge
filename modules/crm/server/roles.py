"""Which AI does which of the CRM's jobs.

    extraction  reading notes and documents into the graph. Quality matters (Claude Opus by default).
    utility     triage and spreadsheet column mapping. Cheap and fast (Gemini Flash by default).
    profiles    each person's overview, answers to questions about them, and lists for the network (presets). Same
                as the app by default, which is the local model unless you chose otherwise. There is no "rules"
                reading of this one.

Each job's provider is a setting (`crm.extraction_provider`, `crm.utility_provider`): "auto" follows the
app-wide provider and fallback chosen in Settings → AI, any one provider by id, or "rules" (no AI: a plain-text
reading that a person always reviews). The keys and models of each
provider live there too.
"""
from pydantic import BaseModel

from core.server import ai, config, resources, settings

ROLES = {
    "extraction": {"label": "Reading notes and documents", "hint": "Finds the people, organizations and relationships in what you add.", "weight": "heavy"},
    "utility": {"label": "Sorting and column mapping", "hint": "Decides what's worth reading, and what the columns in a spreadsheet mean.", "weight": "light"},
    "profiles": {"label": "Overviews and questions", "hint": "Writes each person's overview, answers what you ask about them, and writes lists for the network.", "weight": "light", "rules": False},
}
# "auto" follows the choice made in setup (Settings → AI): the app-wide provider, or the cloud one for heavy jobs. These were
# Claude and Gemini before setup existed; keep_what_people_have() keeps them for anyone who was using them.
OLD_DEFAULTS = {"extraction": "anthropic", "utility": "gemini"}
SETTINGS = {"extraction_provider": "auto", "utility_provider": "auto", "profiles_provider": "auto", "providers_kept": False}
CHOICES = {f"{role}_provider": ("auto", *ai.PROVIDERS, *(("rules",) if info.get("rules", True) else ())) for role, info in ROLES.items()}
ROLES["utility"]["rules_when_local"] = True   # sorting and column mapping: the rules matched a 7B model (PLAN.md, chunk 22a)


def raw(role: str) -> str:
    """What the setting says: "auto", a provider, or "rules"."""
    return settings.section("crm")[f"{role}_provider"]


def choice(role: str) -> str:
    """Who does this job: "rules", or a provider. "auto" follows the app-wide choice for a job this heavy (see ai.resolve)."""
    chosen = ai.resolve(raw(role), ROLES[role]["weight"])
    if raw(role) == "auto" and ROLES[role].get("rules_when_local") and ai.describe(chosen)["local"]:
        return "rules"            # not worth a local model's time; a model you name yourself is still used
    return chosen


def keep_what_people_have() -> None:
    """Once, at startup. These jobs used to default to Claude and Gemini, and a setting nobody changed follows its
    default, so the new "auto" default would quietly move an install that was using them. An install that was in use
    before setup existed, and has a key for the old default, is pinned to it; a new install follows setup instead."""
    from core.server import setup as first_run
    if settings.get_all().get("crm.providers_kept"):
        return
    if first_run.done():
        stored = settings.stored_here()
        for role, old in OLD_DEFAULTS.items():
            if f"crm.{role}_provider" not in stored and settings.get_all().get(f"ai.{old}_api_key"):
                settings.update({f"crm.{role}_provider": old})
    settings.update({"crm.providers_kept": True})


def basic() -> bool:
    """True when a model that runs on this Mac is too small to be trusted with reading notes into the graph: this Mac has
    less memory than app.json's localAiMinGb (what its heaviest job needs to do well locally)."""
    return resources.snapshot()["ram_total_gb"] < float(config.IDENTITY.get("localAiMinGb", 12))


def ai_jobs() -> dict:
    """The module's AI jobs, for setup (Module.ai_jobs)."""
    return {role: {"label": info["label"], "hint": info["hint"], "weight": info["weight"], "choice": lambda r=role: raw(r)}
            for role, info in ROLES.items()}


def structured(role: str, prompt: str, system: str | None, schema: type[BaseModel],
               max_tokens: int | None = None) -> tuple[BaseModel, str]:
    """A structured answer from whoever does this job. Raises ai.AIError; check .provider_down."""
    return ai.structured(prompt, system, schema, choice(role), max_tokens)


def status() -> list[dict]:
    out = []
    for role, info in ROLES.items():
        if choice(role) == "rules":
            d = {"provider": "rules", "label": "Rules (no AI)", "model": "", "ready": True, "reason": "", "local": True}
        else:
            d = ai.describe(choice(role))
        out.append({"role": role, "setting": f"crm.{role}_provider", "choice": raw(role), **info, "rules": info.get("rules", True),
                    "provider": d["provider"], "providerLabel": d["label"], "model": d["model"], "ready": d["ready"],
                    "reason": d["reason"], "local": d["local"]})
    return out
