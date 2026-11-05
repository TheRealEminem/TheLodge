"""The family's list of local AI models: which ones we know, which to suggest, and which are out of date.

One table for every app (it syncs with the rest of core/). It does three jobs:
- ollama_setup.recommended(): the model to offer for download, by how much memory the computer has;
- ai.preferred_ollama_model(): which *installed* model to use when the user hasn't picked one (the earlier a family
  comes in FAMILIES, the better; a model that isn't listed is still usable, it just ranks after the listed ones);
- later, telling someone after an app update that a newer model suits their computer (superseded_by).

Bring-your-own always works: nothing here limits what can be installed or chosen. The table only ranks and suggests.

To refresh it when new models come out: add the new family at the top of FAMILIES (newest, most preferred first), mark
what it replaces as "legacy" with superseded_by, point RECOMMEND at tags that exist on ollama.com/library, and move
UPDATED. Keep old families: they're how an app recognises a model someone already has.

Status: "recommended" (what we'd suggest today), "current" (good, nothing wrong with keeping it), "legacy" (a newer
family replaces it; still works)."""

UPDATED = "2026-11-05"

# What to download, by size of computer. "big" is for 16 GB Macs and up (about 6 GB of video memory on a PC);
# "small" for the rest. Sizes are Ollama's download sizes.
RECOMMEND = {
    "big": "qwen3.5:9b",     # 6.6 GB
    "small": "qwen3.5:4b",   # 3.3 GB
}

# Most preferred first. `thinking`: the model can think before answering and Ollama takes think=false to skip it;
# the app asks it not to (a long hidden reasoning can use up the whole answer budget and leave nothing).
FAMILIES = [
    {"family": "qwen3.5", "status": "recommended", "thinking": True},
    {"family": "qwen3", "status": "current", "thinking": True, "superseded_by": "qwen3.5"},
    {"family": "qwen2.5", "status": "legacy", "thinking": False, "superseded_by": "qwen3.5"},
    {"family": "gemma3", "status": "current", "thinking": False},
    {"family": "llama3.1", "status": "current", "thinking": False},
    {"family": "llama3.2", "status": "current", "thinking": False},
    {"family": "mistral", "status": "current", "thinking": False},
    {"family": "phi4", "status": "current", "thinking": False},
    {"family": "llama3", "status": "legacy", "thinking": False, "superseded_by": "llama3.1"},
]


def family_of(name: str) -> dict | None:
    """The table's entry for an Ollama model name ("qwen3.5:9b" -> qwen3.5), or None for one we don't list."""
    base = (name or "").lower().split(":")[0]
    return next((f for f in FAMILIES if f["family"] == base), None)


def rank(name: str) -> int:
    """How preferred a model's family is: 0 is the best. Models we don't list come after every listed family."""
    entry = family_of(name)
    return FAMILIES.index(entry) if entry else len(FAMILIES)


def can_think(name: str) -> bool:
    """Whether this model thinks before it answers, so a request should say think=false. Only listed models: sending
    think to one that can't makes Ollama refuse the request."""
    entry = family_of(name)
    return bool(entry and entry.get("thinking"))


def recommended(tier: str) -> str:
    """The model to offer for a "big" or "small" computer."""
    return RECOMMEND[tier]


def superseded_by(name: str) -> str | None:
    """The family that replaces this model's, if it has been replaced."""
    entry = family_of(name)
    return entry.get("superseded_by") if entry else None
