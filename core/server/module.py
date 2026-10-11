"""The contract between the host and a module. A module is a folder in modules/ whose __init__.py exposes
MODULE = Module(...); the host loads the ones listed in app.json and wires each part up.

Rules (see ARCHITECTURE.md): a module never imports another module and never reads another module's tables.
It talks to the rest of the app only through the host: events (and the shared contracts), links, search,
jobs, settings and AI.
"""
import importlib
import logging
from dataclasses import dataclass, field
from typing import Callable

from fastapi import APIRouter

from . import db, events, jobs, settings

log = logging.getLogger("core.modules")


@dataclass
class Module:
    id: str                                   # lowercase, used for table names, settings, API paths and URLs
    name: str                                 # shown in the app
    router: APIRouter | None = None           # mounted at /api/<id>
    migrations: list[str] = field(default_factory=list)  # append-only SQL steps for tables named <id>_*
    settings: dict = field(default_factory=dict)          # name -> default, stored as "<id>.<name>"
    choices: dict = field(default_factory=dict)           # name -> allowed values
    jobs: dict[str, Callable] = field(default_factory=dict)        # kind -> handler(job)
    subscribe: dict[str, Callable] = field(default_factory=dict)   # event name (or "prefix.*") -> handler(payload)
    search: Callable[[str, int], list[dict]] | None = None         # (q, limit) -> [{id, title, snippet}]
    describe: Callable[[str], dict | None] | None = None           # id -> {title, href} for links and search
    startup: Callable[[], None] | None = None


_loaded: dict[str, Module] = {}


def load(ids: list[str]) -> list[Module]:
    for module_id in ids:
        module: Module = importlib.import_module(f"modules.{module_id}").MODULE
        if module.id != module_id:
            raise RuntimeError(f"modules/{module_id} calls itself {module.id!r}; the folder name and id must match")
        register(module)
    for module in _loaded.values():
        if module.startup:
            module.startup()
    return list(_loaded.values())


def register(module: Module) -> None:
    """Wires one module up: its tables, settings, jobs and subscriptions. (Tests use it for stand-in modules.)"""
    db.migrate(module.id, module.migrations)
    settings.declare(module.id, module.settings, module.choices)
    for kind, handler in module.jobs.items():
        jobs.register(module.id, kind, handler)
    for name, handler in module.subscribe.items():
        events.subscribe(name, handler)
    _loaded[module.id] = module


def get(module_id: str) -> Module | None:
    return _loaded.get(module_id)


def all_modules() -> list[Module]:
    return list(_loaded.values())


def describe(ref: str) -> dict | None:
    """"notes:abc" -> {"ref", "module", "id", "title", "href"}, or None when it's gone or its module is off."""
    module_id, _, item_id = ref.partition(":")
    module = _loaded.get(module_id)
    if not module or not module.describe:
        return None
    found = module.describe(item_id)
    return {"ref": ref, "module": module_id, "id": item_id, **found} if found else None


def reset() -> None:
    """Tests only."""
    _loaded.clear()
