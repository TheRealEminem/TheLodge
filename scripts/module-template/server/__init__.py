"""__Name__: say in one line what this module is for.

The parts of the contract it doesn't use yet (settings, jobs, subscribe, startup) are in
core/server/module.py; modules/notes uses them all.
"""
from core.server.module import Module

from . import routes, store

MODULE = Module(
    id="__id__",
    name="__Name__",
    router=routes.router,
    migrations=store.MIGRATIONS,
    search=store.search,
    describe=store.describe,
)
