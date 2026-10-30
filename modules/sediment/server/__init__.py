"""Sediment Analysis: how the people you know seem to feel about you, your company, someone else or your product,
read by AI from what's on file about them (a play on sentiment analysis: what settles out of everything you've noted).

What's on file comes from the People module through its "people.dossier" offer; this module never reads People's
tables. Nothing Sediment writes goes back into People.
"""
from core.server import ai, settings
from core.server.module import Module

from . import readings, routes, store

MODULE = Module(
    id="sediment",
    name="Sediment",
    router=routes.router,
    migrations=store.MIGRATIONS,
    settings={"reading_provider": "auto", "transcripts": True},
    choices={"reading_provider": ("auto", *ai.PROVIDERS)},
    jobs={"read": readings.read},
    lanes={"read": "interactive"},
    describe=store.describe,
    export=store.export,
    count=store.count,
    ai_jobs={"readings": {"label": "Sediment readings", "weight": "heavy",
                          "hint": "Judges how someone feels about you, your company or your product, from what's on file.",
                          "choice": lambda: settings.section("sediment")["reading_provider"]}},
)
