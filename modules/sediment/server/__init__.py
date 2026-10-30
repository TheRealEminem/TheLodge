"""Sediment Analysis: how the people you know seem to feel about you, your company, someone else or your product,
read by AI from what's on file about them (a play on sentiment analysis: what settles out of everything you've noted),
and a portrait of each person that a rehearsal can play, marked as a simulation.

What's on file comes from the People module through its "people.dossier" offer; this module never reads People's
tables. Nothing Sediment writes goes back into People.
"""
from core.server import ai, settings
from core.server.module import Module

from . import readings, routes, store, talk

MODULE = Module(
    id="sediment",
    name="Sediment",
    router=routes.router,
    migrations=store.MIGRATIONS,
    settings={"reading_provider": "auto", "talk_provider": "auto", "transcripts": True},
    choices={"reading_provider": ("auto", *ai.PROVIDERS), "talk_provider": ("auto", *ai.PROVIDERS)},
    jobs={"read": readings.read, "portrait": talk.write_portrait, "reply": talk.reply},
    lanes={"read": "interactive", "portrait": "interactive", "reply": "interactive"},
    describe=store.describe,
    export=store.export,
    count=store.count,
    ai_jobs={"readings": {"label": "Sediment readings", "weight": "heavy",
                          "hint": "Judges how someone feels about you, your company or your product, from what's on file.",
                          "choice": lambda: settings.section("sediment")["reading_provider"]},
             "conversations": {"label": "Sediment rehearsals", "weight": "light",
                               "hint": "Writes each person's portrait and plays them when you rehearse a conversation.",
                               "choice": lambda: settings.section("sediment")["talk_provider"]}},
)
