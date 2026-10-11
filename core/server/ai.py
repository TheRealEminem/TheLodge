"""Text generation for every module: a local Ollama model, or any cloud API you have a key for.

Modules call complete(prompt, system) and get (text, provider used). Which provider answers, with which
model, and the fallback when it fails are app-wide settings ("ai.*"), chosen once in Settings → AI.
Local models are unloaded right after use (keep_alive 0) so they don't sit in memory.
"""
import os
import re
from urllib.parse import urlparse

import httpx

from . import settings

OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "0")  # "0" = unload right after the last call
TIMEOUT = httpx.Timeout(600, connect=8)
MAX_TOKENS = 16000
OLLAMA_NUM_CTX = 16384

PROVIDERS = {
    "ollama": {"label": "Ollama", "kind": "local"},
    "anthropic": {"label": "Claude (Anthropic)", "kind": "cloud"},
    "openai": {"label": "OpenAI", "kind": "cloud", "base": "https://api.openai.com/v1"},
    "gemini": {"label": "Google Gemini", "kind": "cloud"},
    "deepseek": {"label": "DeepSeek", "kind": "cloud", "base": "https://api.deepseek.com"},
    "custom": {"label": "OpenAI-compatible", "kind": "custom"},
}
# Claude models that accept server-side refusal fallback ("default" routing picks the substitute).
_CLAUDE_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}

DEFAULTS = {
    "provider": "ollama",
    "fallback": "none",
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.getenv("OLLAMA_MODEL", ""),  # empty = the best installed one
    "anthropic_model": "claude-opus-5-5",
    "anthropic_api_key": "",
    "openai_model": "gpt-5-mini",
    "openai_api_key": "",
    "gemini_model": "gemini-2.5-flash",
    "gemini_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_api_key": "",
    "custom_name": "OpenAI-compatible",
    "custom_base_url": "",
    "custom_model": "",
    "custom_api_key": "",
}
CHOICES = {"provider": tuple(PROVIDERS), "fallback": ("none", *PROVIDERS)}
ENV = {"anthropic_api_key": "ANTHROPIC_API_KEY", "openai_api_key": "OPENAI_API_KEY",
       "gemini_api_key": "GEMINI_API_KEY", "deepseek_api_key": "DEEPSEEK_API_KEY"}


def declare() -> None:
    settings.declare("ai", DEFAULTS, CHOICES, ENV)


class AIError(Exception):
    pass


# ── For modules ────────────────────────────────────────────────────────

def complete(prompt: str, system: str | None = None, choice: str = "auto") -> tuple[str, str]:
    """(text, provider id). Tries your provider, then your fallback. Raises AIError with every reason."""
    cfg = settings.section("ai")
    return run_chain(choice, cfg, lambda pid: generate(pid, cfg, prompt, system))


def local_first() -> bool:
    """True when the first provider tried runs on this machine (so heavy-work rules apply)."""
    cfg = settings.section("ai")
    return is_local(chain("auto", cfg)[0], cfg)


# ── Provider facts ─────────────────────────────────────────────────────

def label(pid: str, cfg: dict) -> str:
    return (cfg.get("custom_name") or "OpenAI-compatible") if pid == "custom" else PROVIDERS[pid]["label"]


def is_local(pid: str, cfg: dict) -> bool:
    if pid != "ollama":
        return False
    return (urlparse(cfg["ollama_url"]).hostname or "") in ("localhost", "127.0.0.1", "::1")


def configured(pid: str, cfg: dict) -> tuple[bool, str]:
    """(ready, reason-if-not). Cheap: no network call except Ollama's model list."""
    if pid == "ollama":
        return (True, "") if _ollama_tags(cfg) else (False, f"Ollama isn't reachable at {cfg['ollama_url']} (or has no models)")
    if pid == "custom":
        if not cfg["custom_base_url"]:
            return False, "Set a base URL for the OpenAI-compatible provider"
        if not cfg["custom_model"]:
            return False, "Pick a model for the OpenAI-compatible provider"
        return True, ""
    if not cfg[f"{pid}_api_key"]:
        return False, f"Add an API key for {PROVIDERS[pid]['label']} in Settings"
    return True, ""


def model_for(pid: str, cfg: dict) -> str:
    if pid == "ollama":
        return cfg["ollama_model"] or preferred_ollama_model(_ollama_tags(cfg))
    return cfg[f"{pid}_model"]


_PREFERRED_FAMILIES = ("qwen3", "qwen2.5", "gemma3", "llama3.1", "llama3.2", "mistral", "phi4", "llama3")


def preferred_ollama_model(tags: list[dict]) -> str:
    """The installed model most likely to follow instructions well: a known family, the biggest up to ~14B."""
    def params(m: dict) -> float:
        text = (m.get("details") or {}).get("parameter_size", "")
        found = re.match(r"([\d.]+)\s*([BM])", text, re.I)
        return float(found.group(1)) / (1000 if found.group(2).upper() == "M" else 1) if found else 0.0

    def rank(m: dict) -> tuple:
        name = m["name"].lower()
        family = next((i for i, f in enumerate(_PREFERRED_FAMILIES) if name.startswith(f)), len(_PREFERRED_FAMILIES))
        size = params(m)
        return (family, size > 15, -size)

    usable = [m for m in tags if "embed" not in m["name"].lower()]
    return min(usable, key=rank)["name"] if usable else ""


def chain(choice: str, cfg: dict) -> list[str]:
    """Which providers to try, in order. 'auto' = your provider, then your fallback."""
    if choice in PROVIDERS:
        return [choice]
    out = [cfg["provider"]]
    if cfg["fallback"] not in ("none", cfg["provider"]):
        out.append(cfg["fallback"])
    return out


def run_chain(choice: str, cfg: dict, fn) -> tuple[object, str]:
    """Calls fn(provider) for each provider in the chain until one succeeds. Returns (result, provider)."""
    errors = []
    for pid in chain(choice, cfg):
        try:
            return fn(pid), pid
        except AIError as e:
            errors.append(f"{label(pid, cfg)}: {e}")
    raise AIError("; ".join(errors))


# ── Calls ──────────────────────────────────────────────────────────────

def generate(pid: str, cfg: dict, prompt: str, system: str | None = None, keep_alive: str | None = None) -> str:
    ok, why = configured(pid, cfg)
    if not ok:
        raise AIError(why)
    if pid == "ollama":
        text = _ollama(cfg, prompt, system, keep_alive or OLLAMA_KEEP_ALIVE)
    elif pid == "anthropic":
        text = _anthropic(cfg, prompt, system)
    elif pid == "gemini":
        text = _gemini(cfg, prompt, system)
    elif pid == "custom":
        text = _openai_compatible(cfg["custom_base_url"], cfg["custom_api_key"], cfg["custom_model"], prompt, system, pid)
    else:
        text = _openai_compatible(PROVIDERS[pid]["base"], cfg[f"{pid}_api_key"], cfg[f"{pid}_model"], prompt, system, pid)
    text = text.strip()
    if not text:
        raise AIError(f"{label(pid, cfg)} returned an empty response")
    return text


def _ollama_tags(cfg: dict) -> list[dict]:
    try:
        r = httpx.get(f"{cfg['ollama_url']}/api/tags", timeout=2)
        r.raise_for_status()
        return r.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        return []


def _ollama(cfg: dict, prompt: str, system: str | None, keep_alive: str) -> str:
    model = model_for("ollama", cfg)
    if not model:
        raise AIError(f"Ollama isn't reachable at {cfg['ollama_url']} (or has no models installed)")
    body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": keep_alive,
            "options": {"num_ctx": OLLAMA_NUM_CTX, "temperature": 0.2}}
    if system:
        body["system"] = system
    return _post(f"{cfg['ollama_url']}/api/generate", json=body).json().get("response") or ""


def _post(url: str, **kw) -> httpx.Response:
    try:
        r = httpx.post(url, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach {urlparse(url).netloc}: {e}") from e
    if r.status_code >= 400:
        raise AIError(f"{urlparse(url).netloc} returned {r.status_code}: {_error_text(r)}")
    return r


def _error_text(r: httpx.Response) -> str:
    try:
        data = r.json()
        err = data.get("error", data)
        return str(err.get("message") if isinstance(err, dict) else err)[:300]
    except ValueError:
        return r.text[:300]


def _anthropic(cfg: dict, prompt: str, system: str | None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"], timeout=600, max_retries=2)
    model = cfg["anthropic_model"]
    params = {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]}
    if system:
        params["system"] = system
    try:
        if model in _CLAUDE_FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs the request on a suitable model.
            msg = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            msg = client.messages.create(**params)
    except anthropic.AuthenticationError as e:
        raise AIError("Claude rejected the API key") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"Claude model '{model}' wasn't found") from e
    except anthropic.RateLimitError as e:
        raise AIError("Claude rate limit hit; try again in a moment") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Claude API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError(f"Couldn't reach the Claude API: {e}") from e
    if msg.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    return "".join(b.text for b in msg.content if b.type == "text")


def _openai_compatible(base: str, key: str, model: str, prompt: str, system: str | None, pid: str) -> str:
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict = {"model": model, "messages": messages}
    if pid == "openai":
        body["max_completion_tokens"] = MAX_TOKENS  # newer OpenAI models reject max_tokens / custom temperature
    elif pid == "deepseek":
        body["max_tokens"] = 8000
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = _post(f"{base}/chat/completions", json=body, headers=headers)
    try:
        return r.json()["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise AIError(f"Unexpected response from {base}") from e


def _gemini(cfg: dict, prompt: str, system: str | None) -> str:
    body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['gemini_model']}:generateContent",
              json=body, headers={"x-goog-api-key": cfg["gemini_api_key"]})
    try:
        parts = r.json()["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, ValueError) as e:
        raise AIError("Gemini returned no text (it may have blocked the request)") from e
    return "".join(p.get("text", "") for p in parts)


# ── Settings screen: model lists and connection tests ─────────────────

def providers() -> list[dict]:
    cfg = settings.section("ai")
    out = []
    for pid, info in PROVIDERS.items():
        ready, reason = configured(pid, cfg) if pid in chain("auto", cfg) else (None, "")
        out.append({"id": pid, "label": label(pid, cfg), "kind": info["kind"], "ready": ready, "reason": reason})
    return out


def list_models(pid: str) -> list[str]:
    cfg = settings.section("ai")
    if pid == "ollama":
        tags = _ollama_tags(cfg)
        if not tags:
            raise AIError(f"Ollama isn't reachable at {cfg['ollama_url']}")
        return [m["name"] for m in tags if "embed" not in m["name"].lower()]
    if pid == "anthropic":
        import anthropic

        if not cfg["anthropic_api_key"]:
            raise AIError("Add an API key first")
        try:
            return [m.id for m in anthropic.Anthropic(api_key=cfg["anthropic_api_key"], timeout=20).models.list()]
        except anthropic.APIError as e:
            raise AIError(f"Claude: {e}") from e
    if pid == "gemini":
        if not cfg["gemini_api_key"]:
            raise AIError("Add an API key first")
        r = httpx.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                      headers={"x-goog-api-key": cfg["gemini_api_key"]}, timeout=20)
        if r.status_code >= 400:
            raise AIError(f"Gemini returned {r.status_code}: {_error_text(r)}")
        return [m["name"].removeprefix("models/") for m in r.json().get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])]
    base = cfg["custom_base_url"] if pid == "custom" else PROVIDERS[pid]["base"]
    key = cfg[f"{pid}_api_key"]
    if not base:
        raise AIError("Set a base URL first")
    if pid != "custom" and not key:
        raise AIError("Add an API key first")
    try:
        r = httpx.get(f"{base}/models", headers={"Authorization": f"Bearer {key}"} if key else {}, timeout=20)
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach {base}: {e}") from e
    if r.status_code >= 400:
        raise AIError(f"{urlparse(base).netloc} returned {r.status_code}: {_error_text(r)}")
    return sorted(m["id"] for m in r.json().get("data", []))


def test(pid: str) -> str:
    cfg = settings.section("ai")
    reply = generate(pid, cfg, "Reply with exactly: OK")
    return f"{label(pid, cfg)} · {model_for(pid, cfg)} replied “{reply[:40]}”"
