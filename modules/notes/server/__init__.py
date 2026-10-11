"""Notes: the sample module. Write a note; an AI summary is made in the background (with your approval
unless "Summarize automatically" is on), and the action items it finds are handed to whoever listens
(the tasks module) through the shared contract.

Copy this folder to start a new module (scripts/new-module does it): it shows every part of the contract.
"""
from core.server.module import Module

from . import routes, store, work

MODULE = Module(
    id="notes",
    name="Notes",
    router=routes.router,
    migrations=store.MIGRATIONS,
    settings={"auto_summarize": False},
    jobs={"summarize": work.summarize},
    search=store.search,
    describe=store.describe,
)
