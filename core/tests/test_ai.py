"""The AI layer with fake transports: nothing here reaches a real model.

What these pin down (each cost a debugging round in DynaCRM): Claude gets a flat strict schema, a streamed call, the
refusal-fallback beta and thinking left alone; failures that say nothing about the text are provider-down, and
failures about the text (refusal, out of output space, wrong shape) are not; OpenAI-compatible servers are tried
from strict to plain and get one repair retry.
"""
from types import SimpleNamespace

import anthropic
import httpx
import pytest
from pydantic import BaseModel

from core.server import ai, ai_adapters, ai_schema


class Person(BaseModel):
    name: str
    email: str | None = None


class Extraction(BaseModel):
    summary: str
    people: list[Person] = []
    date: str | None = None


GOOD = '{"summary": "Met Ana", "people": [{"name": "Ana", "email": ""}], "date": ""}'


@pytest.fixture
def cfg(monkeypatch):
    """Settings for one test: cfg(provider="anthropic", anthropic_api_key="k", ...)."""
    values = dict(ai.DEFAULTS)

    def use(**overrides):
        values.update(overrides)
        return values

    monkeypatch.setattr(ai.settings, "section", lambda namespace: values)
    return use


# ── Schemas ────────────────────────────────────────────────────────────

def test_claude_gets_a_flat_schema_with_every_field_required():
    s = ai_schema.strict_schema(Extraction)
    assert s["required"] == ["summary", "people", "date"] and s["additionalProperties"] is False
    person = s["properties"]["people"]["items"]
    assert person["required"] == ["name", "email"] and "$ref" not in str(s) and "anyOf" not in str(s)
    assert "title" not in s and "default" not in str(s)


def test_other_providers_get_a_plain_schema_that_keeps_optional_fields_optional():
    s = ai_schema.portable_schema(Extraction)
    assert s["required"] == ["summary"] and s["properties"]["date"]["type"] == "string"


def test_blank_strings_become_none_for_optional_fields_only():
    got = Extraction.model_validate(ai_schema.blank_to_none(Extraction, ai_schema.parse_json_text(GOOD)))
    assert got.date is None and got.people[0].email is None and got.people[0].name == "Ana"
    empty = ai_schema.blank_to_none(Person, {"name": "", "email": ""})
    assert empty == {"name": "", "email": None}  # a required field's blank is the model's problem, not ours


def test_json_is_found_inside_fences_and_prose():
    assert ai_schema.parse_json_text('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai_schema.parse_json_text('Here you go: {"a": 1} Hope that helps.') == {"a": 1}
    with pytest.raises(ValueError):
        ai_schema.parse_json_text("no json here")


# ── Claude ─────────────────────────────────────────────────────────────

def message(text=GOOD, stop="end_turn", blocks=None):
    content = blocks if blocks is not None else [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason=stop, id="msg_1",
                           usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def status_error(cls, status, text):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(text, response=httpx.Response(status, request=request), body=None)


@pytest.fixture
def claude(monkeypatch, cfg):
    """Fakes the Anthropic client. claude.reply = a message or an exception; claude.calls records each call."""
    class Fake:
        reply = message()
        calls: list[dict] = []

    fake = Fake()
    fake.calls = []

    class Stream:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get_final_message(self):
            if isinstance(fake.reply, Exception):
                raise fake.reply
            return fake.reply

    class Client:
        def __init__(self, **kw):
            fake.client_args = kw
            self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **kw: self._stream("beta", kw)))
            self.messages = SimpleNamespace(stream=lambda **kw: self._stream("plain", kw))

        def _stream(self, which, kw):
            fake.calls.append({"which": which, **kw})
            return Stream()

    monkeypatch.setattr(anthropic, "Anthropic", Client)
    cfg(provider="anthropic", anthropic_api_key="sk-test")
    return fake


def test_claude_is_streamed_with_the_strict_schema_the_fallback_beta_and_thinking_left_alone(claude):
    got, provider = ai.structured("Notes about Ana", "You extract.", Extraction)
    assert provider == "anthropic" and got.summary == "Met Ana" and got.date is None and got.people[0].email is None
    [call] = claude.calls
    assert call["which"] == "beta" and call["betas"] == ["server-side-fallback-2026-07-01"] and call["fallbacks"] == "default"
    assert call["max_tokens"] == 32000 and call["system"] == "You extract."
    assert "thinking" not in call
    schema = call["output_config"]["format"]["schema"]
    assert call["output_config"]["format"]["type"] == "json_schema" and schema["required"] == ["summary", "people", "date"]
    assert call["messages"] == [{"role": "user", "content": "Notes about Ana"}]


def test_a_model_that_cant_fall_back_uses_the_plain_stream(claude, cfg):
    cfg(anthropic_model="claude-haiku-5-5")
    ai.structured("x", None, Extraction)
    assert claude.calls[0]["which"] == "plain" and "betas" not in claude.calls[0] and "system" not in claude.calls[0]


def test_after_a_server_side_fallback_only_the_continuing_models_text_counts(claude):
    claude.reply = message(blocks=[SimpleNamespace(type="text", text="I can't do that, sorry"),
                                   SimpleNamespace(type="fallback"),
                                   SimpleNamespace(type="text", text=GOOD)])
    assert ai.structured("x", "s", Extraction)[0].summary == "Met Ana"


@pytest.mark.parametrize("error, down", [
    (status_error(anthropic.AuthenticationError, 401, "invalid x-api-key"), True),
    (status_error(anthropic.NotFoundError, 404, "model: claude-nope"), True),
    (status_error(anthropic.RateLimitError, 429, "slow down"), True),
    (status_error(anthropic.APIStatusError, 400, "Your credit balance is too low to access the API"), True),
    (status_error(anthropic.APIStatusError, 400, "Schema is too complex for compilation"), True),
    (status_error(anthropic.APIStatusError, 529, "Overloaded"), True),
    (anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com")), True),
    (status_error(anthropic.APIStatusError, 400, "prompt is too long: 250000 tokens > 200000 maximum"), False),
])
def test_claude_failures_are_provider_down_unless_this_one_text_was_the_problem(claude, error, down):
    claude.reply = error
    with pytest.raises(ai.AIError) as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is down


def test_the_out_of_credit_message_says_what_to_do(claude):
    claude.reply = status_error(anthropic.APIStatusError, 400, "Your credit balance is too low")
    with pytest.raises(ai.AIError, match="out of credit"):
        ai.structured("x", "s", Extraction)


@pytest.mark.parametrize("reply, text", [
    (message(stop="refusal", text=""), "declined"),
    (message(stop="max_tokens", text='{"summary": "cut o'), "ran out of output"),
    (message(text="not json at all"), "didn't match"),
    (message(text='{"people": []}'), "didn't match"),  # summary missing
])
def test_claude_content_failures_are_about_the_text_not_the_provider(claude, reply, text):
    claude.reply = reply
    with pytest.raises(ai.AIError, match=text) as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is False


def test_a_missing_key_is_provider_down(cfg):
    cfg(provider="anthropic", anthropic_api_key="")
    with pytest.raises(ai.AIError, match="API key") as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is True


# ── Ollama ─────────────────────────────────────────────────────────────

@pytest.fixture
def http(monkeypatch):
    """Fakes httpx.post: http.replies is a list of (status, json) answered in order; http.calls records the bodies."""
    class Fake:
        replies: list = []
        calls: list = []

    fake = Fake()
    fake.calls = []

    def post(url, **kw):
        fake.calls.append({"url": url, **kw})
        reply = fake.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        status, body = reply
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", post)
    return fake


@pytest.fixture
def ollama(monkeypatch, cfg):
    monkeypatch.setattr(ai, "_ollama_tags", lambda c: [{"name": "qwen3:8b", "details": {"parameter_size": "8B"}}])
    cfg(provider="ollama")


def chat(content, **extra):
    return 200, {"message": {"content": content}, "done_reason": "stop", **extra}


def test_ollama_gets_the_portable_schema_a_right_sized_context_and_its_own_model(ollama, http):
    http.replies = [chat(GOOD)]
    got, provider = ai.structured("a" * 60000, "sys", Extraction)
    assert provider == "ollama" and got.summary == "Met Ana"
    [call] = http.calls
    body = call["json"]
    assert call["url"].endswith("/api/chat") and body["model"] == "qwen3:8b" and body["stream"] is False
    assert body["format"]["required"] == ["summary"]
    assert body["options"]["num_ctx"] == 32768 and body["messages"][0] == {"role": "system", "content": "sys"}


def test_the_context_window_grows_with_the_prompt_and_stops_at_the_limit():
    assert ai_adapters.ollama_context(100) == 8192
    assert ai_adapters.ollama_context(30000) == 16384
    assert ai_adapters.ollama_context(10 ** 7) == 32768


def test_ollama_down_or_missing_model_is_provider_down(ollama, http):
    http.replies = [httpx.ConnectError("refused")]
    with pytest.raises(ai.AIError, match="Couldn't reach Ollama") as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down
    http.replies = [(404, {"error": "model not found"})]
    with pytest.raises(ai.AIError, match="ollama pull") as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down


def test_ollama_content_failures_are_not_provider_down(ollama, http):
    http.replies = [chat("sorry, I can't")]
    with pytest.raises(ai.AIError, match="didn't match") as e:
        ai.structured("x", "s", Extraction)
    assert not e.value.provider_down
    http.replies = [chat('{"summary": "cut', done_reason="length")]
    with pytest.raises(ai.AIError, match="ran out") as e:
        ai.structured("x", "s", Extraction)
    assert not e.value.provider_down


# ── OpenAI-compatible (OpenAI, Gemini, DeepSeek, custom) ───────────────

def completion(content, finish="stop"):
    return 200, {"choices": [{"message": {"content": content}, "finish_reason": finish}]}


def test_gemini_goes_through_the_compatibility_endpoint_with_a_strict_schema_first(http, cfg):
    cfg(provider="gemini", gemini_api_key="g-key")
    http.replies = [completion(GOOD)]
    got, provider = ai.structured("x", "sys", Extraction)
    assert provider == "gemini" and got.summary == "Met Ana"
    [call] = http.calls
    assert call["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert call["headers"] == {"Authorization": "Bearer g-key"}
    body = call["json"]
    assert body["response_format"]["type"] == "json_schema" and body["max_tokens"] == 16000
    assert body["messages"][0] == {"role": "system", "content": "sys"}  # the schema is enforced, not described


def test_a_server_that_rejects_json_schema_is_tried_with_json_mode_then_plain(http, cfg):
    cfg(provider="custom", custom_base_url="http://localhost:1234/v1", custom_model="m")
    http.replies = [(400, {"error": {"message": "response_format json_schema unsupported"}}),
                    (400, {"error": {"message": "response_format unsupported"}}),
                    completion('```json\n' + GOOD + '\n```')]
    got, _ = ai.structured("x", "sys", Extraction)
    assert got.summary == "Met Ana"
    modes = [c["json"].get("response_format", {}).get("type") for c in http.calls]
    assert modes == ["json_schema", "json_object", None]
    assert "JSON schema" in http.calls[1]["json"]["messages"][0]["content"]  # told the shape in words
    assert "Authorization" not in http.calls[0]["headers"]  # a local server needs no key


def test_a_bad_answer_gets_one_repair_retry_then_gives_up(http, cfg):
    cfg(provider="gemini", gemini_api_key="k")
    http.replies = [completion('{"people": []}'), completion(GOOD)]
    assert ai.structured("x", "sys", Extraction)[0].summary == "Met Ana"
    repair = http.calls[1]["json"]["messages"]
    assert repair[-2] == {"role": "assistant", "content": '{"people": []}'} and "invalid" in repair[-1]["content"]

    http.calls.clear()
    http.replies = [completion("nope"), completion("still nope")]
    with pytest.raises(ai.AIError, match="didn't match") as e:
        ai.structured("x", "sys", Extraction)
    assert not e.value.provider_down and len(http.calls) == 2


@pytest.mark.parametrize("status, text, down", [
    (401, "bad key", True), (403, "forbidden", True), (404, "no such model", True), (429, "quota", True),
    (500, "server fell over", True), (400, "maximum context length is 8192 tokens", False),
])
def test_openai_compatible_failures_are_provider_down_unless_this_text_was_too_long(http, cfg, status, text, down):
    cfg(provider="openai", openai_api_key="k")
    http.replies = [(status, {"error": {"message": text}})] * 3
    with pytest.raises(ai.AIError) as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is down


def test_unreachable_is_provider_down_and_running_out_of_output_is_not(http, cfg):
    cfg(provider="gemini", gemini_api_key="k")
    http.replies = [httpx.ConnectError("no route")]
    with pytest.raises(ai.AIError) as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down
    http.replies = [completion('{"summary": "cu', finish="length")]
    with pytest.raises(ai.AIError, match="ran out") as e:
        ai.structured("x", "s", Extraction)
    assert not e.value.provider_down


def test_each_provider_names_its_output_budget_the_way_it_expects(http, cfg):
    cfg(openai_api_key="k", deepseek_api_key="k")
    http.replies = [completion(GOOD), completion(GOOD)]
    ai.structured("x", "s", Extraction, choice="openai")
    ai.structured("x", "s", Extraction, choice="deepseek", max_tokens=20000)
    openai_body, deepseek_body = http.calls[0]["json"], http.calls[1]["json"]
    assert openai_body["max_completion_tokens"] == 16000 and "max_tokens" not in openai_body
    assert deepseek_body["max_tokens"] == 8000  # DeepSeek's ceiling


# ── Choosing who answers ───────────────────────────────────────────────

def test_a_provider_failure_moves_to_the_fallback_and_a_double_failure_says_both(http, claude, cfg):
    cfg(provider="anthropic", fallback="gemini", gemini_api_key="g")
    claude.reply = status_error(anthropic.APIStatusError, 400, "Your credit balance is too low")
    http.replies = [completion(GOOD)]
    got, provider = ai.structured("x", "s", Extraction)
    assert provider == "gemini" and got.summary == "Met Ana"

    http.replies = [(401, {"error": {"message": "bad key"}})]
    with pytest.raises(ai.AIError, match="out of credit.*Google Gemini") as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is True


def test_a_content_failure_anywhere_means_the_chain_is_not_provider_down(http, claude, cfg):
    cfg(provider="anthropic", fallback="gemini", gemini_api_key="g")
    claude.reply = status_error(anthropic.APIStatusError, 400, "Your credit balance is too low")
    http.replies = [completion("nope"), completion("nope")]
    with pytest.raises(ai.AIError) as e:
        ai.structured("x", "s", Extraction)
    assert e.value.provider_down is False  # the fallback did answer; the text is what it couldn't handle


def test_a_job_can_name_its_own_provider(http, claude, cfg):
    cfg(provider="anthropic", anthropic_api_key="k", gemini_api_key="g")
    http.replies = [completion(GOOD)]
    assert ai.structured("x", "s", Extraction, choice="gemini")[1] == "gemini"
    assert claude.calls == []


def test_describe_says_who_would_answer_and_whether_they_are_ready(cfg):
    cfg(provider="anthropic", anthropic_api_key="", gemini_api_key="g")
    d = ai.describe("auto")
    assert (d["provider"], d["ready"], d["model"], d["local"]) == ("anthropic", False, "", False) and "API key" in d["reason"]
    d = ai.describe("gemini")
    assert (d["provider"], d["ready"], d["model"]) == ("gemini", True, "gemini-flash-latest")


def test_the_test_button_does_a_real_structured_round_trip(http, cfg):
    cfg(gemini_api_key="g")
    http.replies = [completion('{"answer": "OK", "number": 7}')]
    assert "structured output works" in ai.test("gemini")
    http.replies = [completion('{"answer": "OK", "number": 3}')]
    assert "not exactly as asked" in ai.test("gemini")
