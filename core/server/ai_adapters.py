"""Structured output, one adapter per kind of provider. ai.structured() is the way in; this is the how.

    Claude              strict flat schema, streamed, with the refusal-fallback beta, thinking left on
    Ollama              its native /api/chat with `format` (the /v1 shim can't raise the context window)
    OpenAI-compatible   OpenAI, Gemini's compatibility endpoint, DeepSeek, LM Studio, vLLM, anything with
                        /chat/completions: json_schema, then json_object, then plain text, one repair retry

Each takes plain values and returns a validated schema object or raises ai.AIError (see ai.py for what
provider_down means). Lessons that cost a debugging round in DynaCRM are marked ⚑.
"""
import json
import logging
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ValidationError

from .ai import (AIError, PROVIDERS, TIMEOUT, _CLAUDE_FALLBACK_MODELS, _error_text, claude_error, configured, label,
                 model_for, too_long)
from .ai_schema import blank_to_none, parse_json_text, portable_schema, strict_schema

log = logging.getLogger("core.ai")

CLAUDE_MAX_TOKENS = 32000   # ⚑ long extractions; streamed, so a long answer doesn't hit the request timeout
OTHER_MAX_TOKENS = 16000
DEEPSEEK_MAX_TOKENS = 8000  # its ceiling
OLLAMA_OUTPUT_BUDGET = 4096
OLLAMA_MAX_CONTEXT = 32768
OLLAMA_KEEP_ALIVE = "5m"    # a batch of documents shouldn't reload the model for each one
GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"


def generate_structured(pid: str, cfg: dict, prompt: str, system: str | None, schema: type[BaseModel],
                        max_tokens: int | None) -> BaseModel:
    ok, why = configured(pid, cfg)
    if not ok:
        raise AIError(why, provider_down=True)
    system = system or ""
    if pid == "anthropic":
        return _claude(cfg, system, prompt, schema, max_tokens or CLAUDE_MAX_TOKENS)
    if pid == "ollama":
        return _ollama(cfg, system, prompt, schema)
    if pid == "gemini":
        base, key = GEMINI_OPENAI_BASE, cfg["gemini_api_key"]
    elif pid == "custom":
        base, key = cfg["custom_base_url"], cfg["custom_api_key"]
    else:
        base, key = PROVIDERS[pid]["base"], cfg[f"{pid}_api_key"]
    budget = max_tokens or OTHER_MAX_TOKENS
    if pid == "deepseek":
        budget = min(budget, DEEPSEEK_MAX_TOKENS)
    return _openai_compatible(base, key, cfg[f"{pid}_model"], system, prompt, schema, budget,
                              budget_key="max_completion_tokens" if pid == "openai" else "max_tokens",
                              who=label(pid, cfg))


def _validate(schema: type[BaseModel], text: str, who: str) -> BaseModel:
    try:
        return schema.model_validate(blank_to_none(schema, parse_json_text(text)))
    except (ValueError, ValidationError) as e:  # JSONDecodeError and pydantic's ValidationError are ValueErrors
        raise AIError(f"{who}'s answer didn't match the expected structure: {str(e)[:200]}") from e


# ── Claude ─────────────────────────────────────────────────────────────

def _final_text(message) -> str:
    """Text of the answer; after a server-side fallback, only the continuing model's text counts."""
    blocks = list(message.content)
    last_fallback = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
    return "".join(b.text for b in blocks[last_fallback + 1:] if b.type == "text")


def _claude(cfg: dict, system: str, prompt: str, schema: type[BaseModel], max_tokens: int) -> BaseModel:
    import anthropic

    model = cfg["anthropic_model"]
    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"], timeout=900, max_retries=2)
    params = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
        # ⚑ a nested or optional-heavy schema makes Claude answer "Schema is too complex": send the flat one.
        # ⚑ never turn thinking off: current Opus models always think, and effort is the cost control.
        "output_config": {"format": {"type": "json_schema", "schema": strict_schema(schema)}},
    }
    if system:
        params["system"] = system
    try:
        if model in _CLAUDE_FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs the request on a suitable model.
            stream = client.beta.messages.stream(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            stream = client.messages.stream(**params)
        with stream as s:  # ⚑ streamed: a long answer would hit the request timeout otherwise
            message = s.get_final_message()
    except anthropic.APIError as e:
        raise claude_error(e, model) from e
    if message.stop_reason == "refusal":
        raise AIError("Claude declined to process this text")
    if message.stop_reason == "max_tokens":
        raise AIError("Claude ran out of output space before it finished")
    result = _validate(schema, _final_text(message), "Claude")
    usage = message.usage
    log.info("claude %s %s: in=%s out=%s", model, message.id, usage.input_tokens, usage.output_tokens)
    return result


# ── Ollama ─────────────────────────────────────────────────────────────

def ollama_context(chars: int) -> int:
    """Smallest power of two that fits the prompt (~3 characters a token) plus the answer."""
    need = chars // 3 + OLLAMA_OUTPUT_BUDGET
    ctx = 8192
    while ctx < need and ctx < OLLAMA_MAX_CONTEXT:
        ctx *= 2
    return min(ctx, OLLAMA_MAX_CONTEXT)


def _ollama(cfg: dict, system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    model = model_for("ollama", cfg)
    url = cfg["ollama_url"]
    body = {
        "model": model,
        "messages": ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}],
        "format": portable_schema(schema),
        "stream": False,
        "keep_alive": OLLAMA_KEEP_ALIVE,
        "options": {"num_ctx": ollama_context(len(system) + len(prompt)), "temperature": 0.1},
    }
    try:
        r = httpx.post(f"{url}/api/chat", json=body, timeout=httpx.Timeout(1800, connect=8))
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach Ollama at {url}: {e.__class__.__name__}", provider_down=True) from e
    if r.status_code == 404:
        raise AIError(f"The Ollama model '{model}' isn't installed (run: ollama pull {model})", provider_down=True)
    if r.status_code >= 400:
        raise AIError(f"Ollama error {r.status_code}: {r.text[:300]}", provider_down=True)
    data = r.json()
    if data.get("done_reason") == "length":
        raise AIError("The local model ran out of output space before it finished")
    return _validate(schema, (data.get("message") or {}).get("content", ""), "The local model")


# ── OpenAI-compatible ──────────────────────────────────────────────────

def _chat(base: str, key: str, body: dict) -> httpx.Response:
    try:
        return httpx.post(f"{base.rstrip('/')}/chat/completions", json=body, timeout=TIMEOUT,
                          headers={"Authorization": f"Bearer {key}"} if key else {})
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach {urlparse(base).netloc}: {e.__class__.__name__}", provider_down=True) from e


def _openai_compatible(base: str, key: str, model: str, system: str, prompt: str, schema: type[BaseModel],
                       max_tokens: int, budget_key: str, who: str) -> BaseModel:
    host = urlparse(base).netloc
    json_schema = portable_schema(schema)
    user = {"role": "user", "content": prompt}
    hint = "\n\nReply with a single JSON object matching this JSON schema:\n" + json.dumps(json_schema)
    modes = [
        {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": json_schema}},
        {"type": "json_object"},
        None,
    ]
    r = body = None
    for mode in modes:
        strict = mode is not None and mode["type"] == "json_schema"
        # Without a schema-enforcing mode the model has to be told the shape in words.
        sys_text = system if strict else system + hint
        body = {"model": model, budget_key: max_tokens,
                "messages": ([{"role": "system", "content": sys_text}] if sys_text else []) + [user]}
        if mode:
            body["response_format"] = mode
        r = _chat(base, key, body)
        if r.status_code in (401, 403):
            raise AIError(f"{who} rejected the API key", provider_down=True)
        if r.status_code == 404:
            raise AIError(f"The model '{model}' wasn't found at {host}", provider_down=True)
        if r.status_code == 429:
            raise AIError(f"{who} is rate limiting or out of quota; try again later", provider_down=True)
        if r.status_code == 400 and mode is not None and not too_long(_error_text(r)):
            log.info("%s rejected response_format %s: %s", host, mode["type"], _error_text(r))
            continue  # try a less strict output mode
        break
    assert r is not None and body is not None
    if r.status_code >= 400:
        text = _error_text(r)
        raise AIError(f"{who} error {r.status_code}: {text}", provider_down=not too_long(text))

    for attempt in range(2):  # ⚑ one repair retry: the model sees what was wrong with its own answer
        choice = (r.json().get("choices") or [{}])[0]
        content = (choice.get("message") or {}).get("content") or ""
        if choice.get("finish_reason") == "length":
            raise AIError(f"{who} ran out of output space before it finished")
        try:
            return schema.model_validate(blank_to_none(schema, parse_json_text(content)))
        except (ValueError, ValidationError) as e:
            if attempt == 1:
                raise AIError(f"{who}'s answer didn't match the expected structure: {str(e)[:200]}") from e
            repair = {**body, "messages": [
                *body["messages"],
                {"role": "assistant", "content": content[:20000]},
                {"role": "user", "content": f"That JSON is invalid: {str(e)[:500]}\nReply with corrected JSON only."},
            ]}
            r = _chat(base, key, repair)
            if r.status_code >= 400:
                text = _error_text(r)
                raise AIError(f"{who} error {r.status_code}: {text}", provider_down=not too_long(text))
    raise AIError("unreachable")
