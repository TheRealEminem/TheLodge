"""Which AI does which of the CRM's two jobs.

    extraction  reading notes and documents into the graph. Quality matters (Claude Opus by default).
    utility     triage and spreadsheet column mapping. Cheap and fast (Gemini Flash by default).

Each job's provider is a setting (`crm.extraction_provider`, `crm.utility_provider`): "auto" follows the
app-wide provider and fallback chosen in Settings → AI, any one provider by id, or "rules" (no AI: a plain-text
reading that a person always reviews). The keys and models of each
provider live there too.
"""
from pydantic import BaseModel

from core.server import ai, settings

ROLES = {
    "extraction": {"label": "Reading notes and documents", "hint": "Finds the people, organizations and relationships in what you add."},
    "utility": {"label": "Sorting and column mapping", "hint": "Decides what's worth reading, and what the columns in a spreadsheet mean."},
}
SETTINGS = {"extraction_provider": "anthropic", "utility_provider": "gemini"}
CHOICES = {name: ("auto", *ai.PROVIDERS, "rules") for name in SETTINGS}


def choice(role: str) -> str:
    return settings.section("crm")[f"{role}_provider"]


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
        out.append({"role": role, "setting": f"crm.{role}_provider", "choice": choice(role), **info,
                    "provider": d["provider"], "providerLabel": d["label"], "model": d["model"], "ready": d["ready"],
                    "reason": d["reason"], "local": d["local"]})
    return out
