"""The Lodge researching people itself with Gemini. Google is a stand-in here: these check what the app sends, how it
counts the cost, and what it does with the answers, not what Gemini would find."""
import json

import pytest
from crm_helpers import make

from core.server import db, jobs, settings
from modules.crm.server import gemini_research as gr


def answer(text, searches=2, tokens=(1000, 800, 0)):
    return {"candidates": [{"content": {"parts": [{"text": "thinking", "thought": True}, {"text": text}]},
                            "groundingMetadata": {"webSearchQueries": [f"q{i}" for i in range(searches)],
                                                  "groundingChunks": [{"web": {"uri": "https://example.org/a", "title": "example.org"}}]}}],
            "usageMetadata": {"promptTokenCount": tokens[0], "candidatesTokenCount": tokens[1], "thoughtsTokenCount": tokens[2]}}


class Google:
    """Answers generateContent and the Batch API the way Google does, and records what was asked."""

    def __init__(self):
        self.calls, self.batches, self.fail_next = [], {}, None

    def reply(self, model, body):
        system = body["systemInstruction"]["parts"][0]["text"]
        prompt = body["contents"][0]["parts"][0]["text"]
        if system == gr.CHECK_SYSTEM:
            return answer(json.dumps({"same_person": True, "gaps": "No dates for the board seat.",
                                      "follow_ups": ["When did they join the Helio board?", "Who founded Frostline?"]}), searches=0)
        if system == gr.WRITE_SYSTEM:
            name = prompt.split(" — research profile")[0]
            ref = prompt.split("Lodge ref: ")[1][:10]
            return answer(f"{name} — research profile\nLodge ref: {ref}\nIdentity confidence: High. Matched employer.\n\n"
                          f"{name} runs fleet operations. " * 3, searches=0, tokens=(9000, 2000, 0))
        question = prompt.rsplit("Question: ", 1)[-1]
        return answer(f"Answer to: {question}")

    def __call__(self, method, path, **kw):
        self.calls.append((method, path, kw.get("json")))
        if self.fail_next:
            err, self.fail_next = self.fail_next, None
            raise err
        if path.endswith(":generateContent"):
            return self.reply(path.split("/")[1].split(":")[0], kw["json"])
        if path.endswith(":batchGenerateContent"):
            name = f"batches/{len(self.batches) + 1}"
            model = path.split("/")[1].split(":")[0]
            reqs = kw["json"]["batch"]["input_config"]["requests"]["requests"]
            self.batches[name] = {"done": False, "items": [
                {"metadata": r["metadata"], "response": self.reply(model, r["request"])} for r in reqs]}
            return {"name": name}
        if path.startswith("batches/"):
            b = self.batches[path]
            if not b["done"]:
                return {"metadata": {"state": "BATCH_STATE_RUNNING"}}
            return {"metadata": {"state": "BATCH_STATE_SUCCEEDED"}, "response": {"inlinedResponses": {"inlinedResponses": b["items"]}}}
        raise AssertionError(path)


@pytest.fixture
def google(monkeypatch, client):
    g = Google()
    monkeypatch.setattr(gr, "_call", g)
    monkeypatch.setattr(gr, "resolve_link", lambda url: url)
    settings.update({"ai.gemini_api_key": "test-key", "crm.research_budget": 5})
    client.put("/api/crm/me", json={"name": "Alex Rivera"})
    return g


def person(client, name="Jordan Reyes"):
    return make(client, "person", name, attributes={"title": "Head of Fleet", "email": "jordan@frostline.example"})


def run(client, pid):
    return client.get(f"/api/crm/people/{pid}/research/gemini").json()["run"]


def advance():
    jobs.enqueue("crm", "research_advance", "scheduled")
    jobs.drain()


def test_a_quick_run_asks_six_questions_writes_the_report_and_files_it_for_review(client, google):
    jordan = person(client)
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "level": "quick", "batch": False})
    assert r.status_code == 202 and r.json()["started"] == 1
    jobs.drain()
    done = run(client, jordan["id"])
    assert done["status"] == "done" and done["searches"] == 12
    asks = [c for c in google.calls if c[2] and c[2].get("tools")]
    assert len(asks) == 6 and all("gemini-3.5-flash-lite" in c[1] for c in google.calls)
    assert "jordan@frostline.example" not in json.dumps(google.calls)            # the domain only, never the address
    assert "frostline.example" in json.dumps(asks)
    # 6 answers of 1000 in / 800 out, one report of 9000 / 2000, at Flash-Lite's prices, plus 12 searches
    tokens = (6 * 1000 + 9000) * 0.30 / 1e6 + (6 * 800 + 2000) * 2.50 / 1e6
    assert done["cost"] == pytest.approx(tokens + 12 * 0.014, abs=1e-4)
    item = client.get(f"/api/crm/ingest/jobs/{done['inbox_id']}").json()
    assert item["payload"]["subject_id"] == jordan["id"] and "about $0.19" in item["raw_text"]
    assert "Gemini 3.5 Flash-Lite" in item["raw_text"] and f"Lodge ref: {jordan['id'][:10]}" in item["raw_text"]


def test_batch_runs_go_together_and_cost_half_for_tokens(client, google):
    a, b = person(client), person(client, "Priya Nair")
    client.post("/api/crm/research/gemini", json={"person_ids": [a["id"], b["id"]], "level": "quick", "batch": True})
    jobs.drain()
    assert list(google.batches) == ["batches/1"] and len(google.batches["batches/1"]["items"]) == 12   # both people, one batch
    assert run(client, a["id"])["status"] == "running"
    advance()
    assert run(client, a["id"])["stage"] == "ask"                                 # Google isn't done yet
    google.batches["batches/1"]["done"] = True
    advance()                                                                      # answers in, the reports go out
    assert list(google.batches) == ["batches/1", "batches/2"] and run(client, a["id"])["stage"] == "write"
    google.batches["batches/2"]["done"] = True
    advance()
    done = run(client, a["id"])
    tokens = ((6 * 1000 + 9000) * 0.30 / 1e6 + (6 * 800 + 2000) * 2.50 / 1e6) / 2
    assert done["status"] == "done" and done["cost"] == pytest.approx(tokens + 12 * 0.014, abs=1e-4)
    assert run(client, b["id"])["status"] == "done"


def test_best_has_the_pro_model_check_and_ask_again_before_it_writes(client, google):
    jordan = person(client)
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "level": "best", "batch": False})
    jobs.drain()
    assert run(client, jordan["id"])["status"] == "done"
    models = [c[1].split("/")[1].split(":")[0] for c in google.calls]
    assert models == ["gemini-3.8-flash"] * 6 + ["gemini-4-argon"] + ["gemini-3.8-flash"] * 2 + ["gemini-4-argon"]
    row = db.one("SELECT findings FROM crm_research_runs WHERE entity_id = ?", (jordan["id"],))
    follow = [f for f in json.loads(row["findings"]) if f.get("follow_up")]
    assert [(f["question"], f["text"]) for f in follow] == [                     # each answer under its own question
        ("When did they join the Helio board?", "Answer to: When did they join the Helio board?"),
        ("Who founded Frostline?", "Answer to: Who founded Frostline?")]


def test_the_budget_stops_new_runs_and_says_so(client, google):
    jordan = person(client)
    settings.update({"crm.research_budget": 0})
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "level": "quick"}).json()
    assert r["started"] == 0 and "budget" in r["skipped"][0]["reason"]


def test_without_a_key_nothing_starts(client, google):
    settings.update({"ai.gemini_api_key": ""})
    r = client.post("/api/crm/research/gemini", json={"person_ids": [person(client)["id"]]})
    assert r.status_code == 422 and "Gemini API key" in r.json()["detail"]


def test_google_being_busy_waits_and_carries_on(client, google):
    jordan = person(client)
    google.fail_next = gr.GoogleError(429, "Resource exhausted")
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "batch": False})
    jobs.drain()
    waiting = run(client, jordan["id"])
    assert waiting["status"] == "waiting" and "Resource exhausted" in waiting["error"]
    advance()
    assert run(client, jordan["id"])["status"] == "done"


def test_a_first_name_alone_and_someone_already_being_researched_are_skipped(client, google):
    jordan, cher = person(client), make(client, "person", "Cher")
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]], "batch": True})
    r = client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"], cher["id"]]}).json()
    assert r["started"] == 0 and {s["id"] for s in r["skipped"]} == {jordan["id"], cher["id"]}


def test_estimates_rise_with_the_level_and_batch_halves_the_tokens(google):
    q, qb, b, best = gr.estimate("quick", False), gr.estimate("quick", True), gr.estimate("better", False), gr.estimate("best", False)
    assert qb < q < b < best
    searches = 12 * gr.SEARCH_PRICE
    assert (qb - searches) == pytest.approx((q - searches) / 2, abs=1e-3)


def test_without_a_choice_it_uses_better_through_batch(client, google):
    jordan = person(client)
    client.post("/api/crm/research/gemini", json={"person_ids": [jordan["id"]]})
    jobs.drain()
    started = run(client, jordan["id"])
    assert started["level"] == "better" and started["batch"] and started["status"] == "running"
    assert list(google.batches) == ["batches/1"] and "gemini-3.8-flash" in google.calls[0][1]
