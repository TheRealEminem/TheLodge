"""Settings, stored in the database so the server (jobs, providers, modules) can act on them.

Each module declares its own settings under its id as namespace ("notes.auto_summarize"); the core owns
"core.*" and "ai.*". A declared default can be preset from the environment as <PREFIX>_<NAMESPACE>_<NAME>
(e.g. STARTER_AI_PROVIDER=anthropic), handy for a server install. Values saved in the app win.

Secrets (names ending in _api_key, _token or _secret) are write-only from the web app's point of view: they're never
sent back, only a hint of what's stored ("…1234").

A few settings are shared with the other family apps on this Mac (family.py: the AI settings, your name, the
appearance, Lockdown): reading one gives the family's value, and saving one saves it for every family app as well as here.
"""
import json
import os

from . import config, db, family

_defaults: dict[str, object] = {}
_choices: dict[str, tuple] = {}
_env_names: dict[str, str] = {}


def declare(namespace: str, defaults: dict, choices: dict | None = None, env: dict | None = None) -> None:
    """choices: allowed values for some keys. env: extra environment variable names people already use
    for a key (e.g. {"anthropic_api_key": "ANTHROPIC_API_KEY"})."""
    for key, value in defaults.items():
        _defaults[f"{namespace}.{key}"] = value
    for key, allowed in (choices or {}).items():
        _choices[f"{namespace}.{key}"] = tuple(allowed)
    for key, name in (env or {}).items():
        _env_names[f"{namespace}.{key}"] = name


def is_secret(key: str) -> bool:
    return key.endswith(("_api_key", "_token", "_secret"))


def _env_default(key: str, default):
    raw = config.env(key.replace(".", "_").upper())
    if raw is None and key in _env_names:
        raw = os.getenv(_env_names[key])
    if raw is None:
        return default
    if isinstance(default, bool):
        return raw.lower() in ("1", "true", "yes", "on")
    if isinstance(default, (int, float)) and not isinstance(default, bool):
        return type(default)(raw)
    if isinstance(default, list):
        return [part.strip() for part in raw.split(",") if part.strip()]
    return raw


def stored_here() -> dict:
    """What this app itself has saved, before the family's shared values are laid over it."""
    return {r["key"]: json.loads(r["value"]) for r in db.query("SELECT key, value FROM core_settings")}


def get_all() -> dict:
    """Every setting with its effective value, secrets included. For server use only."""
    stored = stored_here()
    if family.sharing(stored):
        stored.update({k: v for k, v in family.values().items() if k in _defaults})
    out = {}
    for key, default in _defaults.items():
        value = stored.get(key)
        if value is None or (is_secret(key) and value == ""):  # unset (or a cleared secret): use the environment
            value = _env_default(key, default)
        out[key] = value
    return out


def section(namespace: str) -> dict:
    """One namespace's settings without the prefix: section("ai")["provider"]."""
    cut = len(namespace) + 1
    return {k[cut:]: v for k, v in get_all().items() if k.startswith(namespace + ".")}


def public() -> dict:
    """Settings for the web app: secrets blanked, with a short hint of what's stored."""
    values = get_all()
    hints = {}
    for key in [k for k in values if is_secret(k)]:
        secret = values[key]
        hints[key] = f"…{secret[-4:]}" if len(secret) >= 8 else ("set" if secret else None)
        values[key] = ""
    return {"values": values, "secret_hints": hints}


def update(changes: dict) -> dict:
    """changes: {"notes.auto_summarize": False, …}. Raises ValueError with a readable message."""
    for key, value in changes.items():
        if key not in _defaults:
            raise ValueError(f"Unknown setting: {key}")
        default = _defaults[key]
        if not isinstance(value, type(default)) or (isinstance(value, bool) != isinstance(default, bool)):
            raise ValueError(f"{key} must be a {type(default).__name__}")
        if key in _choices and value not in _choices[key]:
            raise ValueError(f"{key} must be one of {', '.join(map(str, _choices[key]))}")
        if key.endswith("_url") and value:
            if not value.startswith(("http://", "https://")):
                raise ValueError(f"{key} must start with http:// or https://")
            changes[key] = value.rstrip("/")
    clean = {key: (value.strip() if is_secret(key) else value) for key, value in changes.items()}
    with db.connect() as conn:
        for key, value in clean.items():
            conn.execute(
                "INSERT INTO core_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
    if family.sharing(stored_here()):
        family.put(clean)                       # the shared ones, for every family app on this Mac
    return public()


def reset() -> None:
    """Tests only."""
    _defaults.clear()
    _choices.clear()
    _env_names.clear()
