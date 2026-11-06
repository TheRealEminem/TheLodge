"""Text generation for every module: a local Ollama model, or any cloud API you have a key for.

Modules call complete(prompt, system) and get (text, provider used), or structured(prompt, system, Schema) and
get (a validated Schema object, provider used). Which provider answers, with which model, and the fallback
when it fails are app-wide settings ("ai.*"), chosen once in Settings → AI. A module can name a provider for
one of its jobs (choice="anthropic"), and a model per provider for it (models={"anthropic": "claude-sonnet-5-5"});
"auto" and a provider not named in models mean the app-wide ones.
Local models are unloaded right after use (keep_alive 0) so they don't sit in memory.
Every provider's attempt goes through attempt(), which writes what it used and cost to the usage log (pricing.py).
While Lockdown is on (lockdown.py), only providers on this Mac are ready (configured()), and attempt() stops the
others before anything is sent: it raises Locked, which a job parks on until Lockdown is off.

Failures come in two kinds (AIError.provider_down). A *provider* failure says nothing about the text: no credit,
a wrong key or model, a rate limit, unreachable, any server error. Every other request would fail the same
way, so a caller doing a batch should stop and wait rather than carry on. A *content* failure (the model
refused, ran out of output, or answered in the wrong shape) is about this text only.
"""
import os
import re
import threading
import time
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from . import lockdown, model_catalog, module, pricing, resources, settings, usage

OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "0")  # "0" = unload right after the last call
TIMEOUT = httpx.Timeout(600, connect=8)
MAX_TOKENS = 16000
OLLAMA_NUM_CTX = 16384
OLLAMA_NUM_PREDICT = 4096         # a local model that never stops writing costs a few minutes, not half an hour
OLLAMA_TIMEOUT = httpx.Timeout(900, connect=8)

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
    "warn_over": 1,              # dollars: a job estimated to cost this much or more asks first (0 = never ask)
    "path": "",                  # where AI runs, from setup: "" (not chosen), "local", "mixed" or "cloud"
    "heavy_provider": "auto",    # for the jobs modules call heavy (reading a long document): "auto" = the same as provider
    "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434"),
    "ollama_model": os.getenv("OLLAMA_MODEL", ""),  # empty = the best installed one
    "model_suggestion_dismissed": "",  # the suggested model someone said "not now" to (shared, so once for every family app)
    "anthropic_model": "claude-opus-5-5",
    "anthropic_api_key": "",
    "openai_model": "gpt-5-mini",
    "openai_api_key": "",
    "gemini_model": "gemini-flash-latest",   # gemini-2.5-flash is closed to new accounts (as Trailmix found)
    "gemini_api_key": "",
    "deepseek_model": "deepseek-chat",
    "deepseek_api_key": "",
    "custom_name": "OpenAI-compatible",
    "custom_base_url": "",
    "custom_model": "",
    "custom_api_key": "",
}
PATHS = ("local", "mixed", "cloud")
CHOICES = {"provider": tuple(PROVIDERS), "fallback": ("none", *PROVIDERS), "path": ("", *PATHS),
           "heavy_provider": ("auto", *PROVIDERS)}
ENV = {"anthropic_api_key": "ANTHROPIC_API_KEY", "openai_api_key": "OPENAI_API_KEY",
       "gemini_api_key": "GEMINI_API_KEY", "deepseek_api_key": "DEEPSEEK_API_KEY"}


def declare() -> None:
    settings.declare("ai", DEFAULTS, CHOICES, ENV)


class AIError(Exception):
    """provider_down: this isn't about the text asked about, so stop and retry later (see the module note)."""

    def __init__(self, message: str, *, provider_down: bool = False):
        super().__init__(message)
        self.provider_down = provider_down


class Locked(AIError, lockdown.Blocked):
    """Lockdown stopped a call to a cloud provider before anything was sent. Also a jobs.Wait: a job that meets it
    parks with this reason and goes again when Lockdown is off."""


LOCKED_OUT = lockdown.WHY


# ── For modules ────────────────────────────────────────────────────────

def complete(prompt: str, system: str | None = None, choice: str = "auto", purpose: str | None = None,
             models: dict[str, str] | None = None) -> tuple[str, str]:
    """(text, provider id). Tries your provider, then your fallback. Raises AIError with every reason.
    purpose: what this is for in a few words, so Settings → AI → Usage can say where the spending went.
    models: a model to use instead of the app-wide one, by provider id (see with_models)."""
    cfg = with_models(settings.section("ai"), models)
    with usage.purpose(purpose):
        return run_chain(choice, cfg, "complete", lambda pid, meter: generate(pid, cfg, prompt, system, meter=meter))


def structured(prompt: str, system: str | None, schema: type[BaseModel], choice: str = "auto",
               max_tokens: int | None = None, purpose: str | None = None,
               models: dict[str, str] | None = None) -> tuple[BaseModel, str]:
    """(an instance of schema, provider id). The reply is constrained to the schema where the provider can do
    that, and checked either way. Optional fields may come back as None. max_tokens: the output budget
    (default 32000 for Claude, 16000 elsewhere). purpose, models: as for complete(). Raises AIError; check .provider_down."""
    from . import ai_adapters

    cfg = with_models(settings.section("ai"), models)
    with usage.purpose(purpose):
        return run_chain(choice, cfg, "structured",
                         lambda pid, meter: ai_adapters.generate_structured(pid, cfg, prompt, system, schema, max_tokens, meter))


def resolve(choice: str, weight: str = "light") -> str:
    """What "auto" means for a job of this weight. Light jobs follow the app-wide provider. A heavy job follows it too,
    unless setup put heavy jobs on a cloud AI ("mixed"): then that one. Anything else is returned as it is."""
    if choice == "auto" and weight == "heavy":
        heavy = settings.section("ai")["heavy_provider"]
        if heavy != "auto":
            return heavy
    return choice


def apply_path(path: str, cloud: str = "") -> None:
    """Setup's choice. local: everything on Ollama. mixed: light jobs on Ollama, heavy ones on `cloud`. cloud: everything
    on `cloud`. The cloud provider needs its key (saved separately); Lockdown is off for the last two, since they
    leave this computer."""
    if path not in PATHS:
        raise ValueError("Choose local, mixed or cloud")
    if path != "local" and (cloud not in PROVIDERS or PROVIDERS[cloud]["kind"] == "local"):
        raise ValueError("Choose which cloud AI to use")
    changes: dict = {"ai.path": path, "ai.fallback": "none"}
    if path == "local":
        changes.update({"ai.provider": "ollama", "ai.heavy_provider": "auto"})
    elif path == "mixed":
        changes.update({"ai.provider": "ollama", "ai.heavy_provider": cloud})
    else:
        changes.update({"ai.provider": cloud, "ai.heavy_provider": "auto"})
    if path != "local":
        changes[lockdown.KEY] = False
    settings.update(changes)


def with_models(cfg: dict, models: dict[str, str] | None) -> dict:
    """The AI settings with a job's own models laid over the app-wide ones. A blank model or an unknown provider
    changes nothing, so a job's model only ever goes to the provider it was chosen for."""
    picked = {f"{pid}_model": m.strip() for pid, m in (models or {}).items() if pid in PROVIDERS and (m or "").strip()}
    return {**cfg, **picked} if picked else cfg


def describe(choice: str = "auto", models: dict[str, str] | None = None) -> dict:
    """Which provider and model a job would use right now, and whether it's ready. For Settings screens."""
    cfg = with_models(settings.section("ai"), models)
    pid = chain(choice, cfg)[0]
    ready, reason = configured(pid, cfg)
    return {"provider": pid, "label": label(pid, cfg), "model": model_for(pid, cfg) if ready else "",
            "ready": ready, "reason": reason, "local": is_local(pid, cfg)}


def local_first() -> bool:
    """True when the first provider tried runs on this machine (so heavy-work rules apply)."""
    cfg = settings.section("ai")
    return is_local(chain("auto", cfg)[0], cfg)


# ── Provider facts ─────────────────────────────────────────────────────

def label(pid: str, cfg: dict) -> str:
    if pid == "custom":
        return cfg.get("custom_name") or "OpenAI-compatible"
    return PROVIDERS[pid]["label"] if pid in PROVIDERS else pid


def is_local(pid: str, cfg: dict) -> bool:
    return pid == "ollama" and lockdown.local(cfg["ollama_url"])


def is_free(pid: str, cfg: dict) -> bool:
    """Costs nothing per call: Ollama, wherever it runs, or an OpenAI-compatible server on this machine."""
    return pid == "ollama" or (pid == "custom" and lockdown.local(cfg.get("custom_base_url", "")))


def runs_here(pid: str, cfg: dict) -> bool:
    """The model runs on this Mac: Ollama or an OpenAI-compatible server, at a local address. Only these answer while
    Lockdown is on (an Ollama on another machine is beyond this Mac too)."""
    if pid == "ollama":
        return lockdown.local(cfg.get("ollama_url"))
    return pid == "custom" and lockdown.local(cfg.get("custom_base_url"))


def locked_out(pid: str, cfg: dict) -> bool:
    """Lockdown is on and this provider is beyond this Mac."""
    return not runs_here(pid, cfg) and lockdown.on()


def configured(pid: str, cfg: dict) -> tuple[bool, str]:
    """(ready, reason-if-not). Cheap: no network call except Ollama's model list. The one choke point: while Lockdown
    is on, a provider beyond this Mac is never ready."""
    if locked_out(pid, cfg):
        return False, LOCKED_OUT
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


def require(pid: str, cfg: dict) -> None:
    """Raises unless pid can take a call now: Locked when Lockdown stops it, AIError for anything else."""
    ok, why = configured(pid, cfg)
    if not ok:
        raise (Locked if why == LOCKED_OUT else AIError)(why, provider_down=True)


def model_for(pid: str, cfg: dict) -> str:
    """The model a provider uses. An empty setting (a cleared field in Settings) means the default, never a
    request for a model named "" (Gemini answers that with a 404)."""
    if pid == "ollama":
        return cfg["ollama_model"] or preferred_ollama_model(_ollama_tags(cfg))
    return (cfg.get(f"{pid}_model") or "").strip() or DEFAULTS.get(f"{pid}_model", "")


def preferred_ollama_model(tags: list[dict]) -> str:
    """The installed model most likely to follow instructions well: the best family in the model catalog, then the
    biggest up to ~14B. A model the catalog doesn't list is still used, after the listed ones."""
    def params(m: dict) -> float:
        text = (m.get("details") or {}).get("parameter_size", "")
        found = re.match(r"([\d.]+)\s*([BM])", text, re.I)
        return float(found.group(1)) / (1000 if found.group(2).upper() == "M" else 1) if found else 0.0

    def rank(m: dict) -> tuple:
        size = params(m)
        return (model_catalog.rank(m["name"]), size > 15, -size)

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


def run_chain(choice: str, cfg: dict, call: str, fn) -> tuple[object, str]:
    """Calls fn(provider, meter) for each provider in the chain until one succeeds. Returns (result, provider)."""
    errors: list[AIError] = []
    reasons = []
    for pid in chain(choice, cfg):
        try:
            return attempt(pid, cfg, call, fn), pid
        except Locked as e:
            errors.append(e)
        except AIError as e:
            errors.append(e)
            reasons.append(f"{label(pid, cfg)}: {e}")
    if any(isinstance(e, Locked) for e in errors):
        # A provider Lockdown stopped might have answered: the job waits for Lockdown to be off rather than failing.
        raise Locked("; ".join([LOCKED_OUT, *reasons]), provider_down=True)
    # Provider-down only if every provider tried failed for reasons that have nothing to do with the text.
    raise AIError("; ".join(reasons), provider_down=all(e.provider_down for e in errors))


def attempt(pid: str, cfg: dict, call: str, fn, asker: tuple[str, str] | None = None):
    """One provider's go at a call ("complete" or "structured"): fn(pid, meter) does it and reports the tokens.
    The one place AI calls are counted: what it used and cost go in the usage log, whether it worked or not.
    asker: (module, job) when it isn't the job running in this thread. While Lockdown is on, a provider beyond this
    Mac is stopped here, before fn runs: the log shows it, at no cost, and Locked is raised."""
    meter = pricing.Meter(pid, cfg.get(f"{pid}_model", ""), free=is_free(pid, cfg), asker=asker)
    if locked_out(pid, cfg):
        meter.record(call, error=LOCKED_OUT, stopped=True)
        raise Locked(LOCKED_OUT, provider_down=True)
    try:
        result = fn(pid, meter)
    except Exception as e:
        meter.record(call, error=str(e) or type(e).__name__)
        raise
    meter.record(call)
    return result


# ── Calls ──────────────────────────────────────────────────────────────

def generate(pid: str, cfg: dict, prompt: str, system: str | None = None, keep_alive: str | None = None,
             meter: pricing.Meter | None = None) -> str:
    """meter: where the tokens are reported (attempt() gives one; without it they aren't recorded)."""
    meter = meter or pricing.Meter(pid)
    require(pid, cfg)
    if pid == "ollama":
        wait_for_memory(cfg)
        text = _ollama(cfg, prompt, system, keep_alive or OLLAMA_KEEP_ALIVE, meter)
    elif pid == "anthropic":
        text = _anthropic(cfg, prompt, system, meter)
    elif pid == "gemini":
        text = _gemini(cfg, prompt, system, meter)
    elif pid == "custom":
        text = _openai_compatible(cfg["custom_base_url"], cfg["custom_api_key"], model_for(pid, cfg), prompt, system, pid,
                                  meter)
    else:
        text = _openai_compatible(PROVIDERS[pid]["base"], cfg[f"{pid}_api_key"], model_for(pid, cfg), prompt, system, pid,
                                  meter)
    text = text.strip()
    if not text:
        raise AIError(f"{label(pid, cfg)} returned an empty response")  # about this text, not the provider
    return text


TAGS_SECONDS = 10           # how long one answer from Ollama's model list stands in for the next
_tags: dict[str, tuple[float, list[dict]]] = {}   # Ollama address -> (when asked, its models); a miss is kept too
_tags_lock = threading.Lock()


def _ollama_tags(cfg: dict, fresh: bool = False) -> list[dict]:
    """Ollama's installed models. Asked for by every readiness check, which the web app makes on every change it
    hears of, so one answer (or one failure to answer, which can take the whole timeout when the address is a machine
    that's off) stands for TAGS_SECONDS. fresh: ask now whatever was kept (a button someone just pressed)."""
    url = cfg["ollama_url"]
    if not lockdown.may_reach(url):     # an Ollama on another machine is beyond this computer too
        return []
    now = time.monotonic()
    with _tags_lock:
        kept = _tags.get(url)
        if kept and not fresh and now - kept[0] < TAGS_SECONDS:
            return kept[1]
    try:
        r = httpx.get(f"{url}/api/tags", timeout=2)
        r.raise_for_status()
        models = r.json().get("models", [])
    except (httpx.HTTPError, ValueError):
        models = []
    with _tags_lock:
        _tags[url] = (now, models)
    return models


def ollama_size_gb(cfg: dict, model: str) -> float:
    """What a model weighs on disk, which is close to what it takes in memory (0 if Ollama doesn't list it)."""
    for m in _ollama_tags(cfg):
        if m["name"] == model:
            return float(m.get("size") or 0) / resources.GB
    return 0.0


def _ollama_loaded(cfg: dict, model: str) -> bool:
    """Is the model already in memory (Ollama keeps one for a few minutes after a call)? Then it costs nothing more."""
    try:
        r = httpx.get(f"{cfg['ollama_url']}/api/ps", timeout=2)
        r.raise_for_status()
        return any(m.get("name") == model or m.get("model") == model for m in r.json().get("models", []))
    except (httpx.HTTPError, ValueError):
        return False


def memory_reason(cfg: dict) -> str | None:
    """Why the local model can't be started now, or None. Only a model on this Mac needs room; another machine's does not."""
    if not is_local("ollama", cfg):
        return None
    model = model_for("ollama", cfg)
    size = ollama_size_gb(cfg, model) if model else 0.0
    if not size or _ollama_loaded(cfg, model):
        return None
    return resources.check(size * 1.15 + 0.5, f"The model {model}")    # the weights, plus its working memory


def wait_for_memory(cfg: dict) -> None:
    """Raises a provider-down AIError (so jobs park, saying why) when this Mac hasn't room for the local model."""
    why = memory_reason(cfg)
    if why:
        raise AIError(why, provider_down=True)


def memory_ready() -> bool:
    """For the scheduler: is there room for the local model now? (Also true when no local model is set up.)"""
    return memory_reason(settings.section("ai")) is None


def _ollama(cfg: dict, prompt: str, system: str | None, keep_alive: str, meter: pricing.Meter) -> str:
    model = meter.model = model_for("ollama", cfg)
    if not model:
        raise AIError(f"Ollama isn't reachable at {cfg['ollama_url']} (or has no models installed)", provider_down=True)
    body = {"model": model, "prompt": prompt, "stream": False, "keep_alive": keep_alive,
            "options": {"num_ctx": OLLAMA_NUM_CTX, "num_predict": OLLAMA_NUM_PREDICT, "temperature": 0.2}}
    if model_catalog.can_think(model):
        body["think"] = False    # a thinking model would spend the answer budget on hidden reasoning
    if system:
        body["system"] = system
    data = _post(f"{cfg['ollama_url']}/api/generate", json=body, timeout=OLLAMA_TIMEOUT).json()
    ollama_usage(data, meter)
    return data.get("response") or ""


# Reading a reply's token counts never fails the call: a count that isn't a number is left unknown.
_n = pricing.count


def ollama_usage(data: dict, meter: pricing.Meter) -> None:
    meter.add(_n(data.get("prompt_eval_count")), _n(data.get("eval_count")))


def openai_usage(data: dict, meter: pricing.Meter) -> None:
    """Tokens from an OpenAI-style reply. Output is everything billed past the prompt, so thinking counts even
    where a server reports it only in total_tokens. Cache reads: OpenAI's and Gemini's cached_tokens, DeepSeek's
    prompt_cache_hit_tokens."""
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    prompt, out, total = _n(usage.get("prompt_tokens")), _n(usage.get("completion_tokens")), _n(usage.get("total_tokens"))
    if prompt is not None and total is not None:
        out = max(out or 0, total - prompt)
    details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cached = _n(details.get("cached_tokens")) or _n(usage.get("prompt_cache_hit_tokens")) or 0
    meter.add(prompt, out, cached, model=data.get("model"))


def claude_usage(message, meter: pricing.Meter) -> None:
    """Claude's tokens. After a refusal fell back, usage.iterations has one entry per model that ran (the top-level
    usage is only the one that answered): the declined attempts ran on the model asked for, the rest on the model
    that answered. Cache reads and writes are input too (this app doesn't ask Claude to cache, so there are none)."""
    usage = getattr(message, "usage", None)
    answered = getattr(message, "model", None)
    for it in getattr(usage, "iterations", None) or [usage]:
        cached = _n(getattr(it, "cache_read_input_tokens", 0)) or 0
        written = _n(getattr(it, "cache_creation_input_tokens", 0)) or 0
        inp = _n(getattr(it, "input_tokens", None))
        ran = getattr(it, "model", None) or (meter.model if getattr(it, "type", "") == "message" else answered)
        meter.add(None if inp is None else inp + cached + written, _n(getattr(it, "output_tokens", None)), cached, model=ran)


def _post(url: str, timeout: httpx.Timeout = TIMEOUT, **kw) -> httpx.Response:
    try:
        r = httpx.post(url, timeout=timeout, **kw)
    except httpx.HTTPError as e:
        raise AIError(f"Couldn't reach {urlparse(url).netloc}: {e}", provider_down=True) from e
    if r.status_code >= 400:
        text = _error_text(r)
        raise AIError(f"{urlparse(url).netloc} returned {r.status_code}: {text}", provider_down=not too_long(text))
    return r


def too_long(text: str) -> bool:
    """An error that says this input was too big for the model: about the text, so not provider-down."""
    t = text.lower()
    return "prompt is too long" in t or "too many tokens" in t or ("context" in t and ("length" in t or "window" in t)) \
        or "maximum context" in t


def _error_text(r: httpx.Response) -> str:
    try:
        data = r.json()
        err = data.get("error", data)
        return str(err.get("message") if isinstance(err, dict) else err)[:300]
    except ValueError:
        return r.text[:300]


def claude_error(e, model: str) -> AIError:
    """An Anthropic SDK error as an AIError. Only an over-long input is specific to the text; any other request
    error (bad key, model or schema, no credit, rate limit, outage) will hit every request."""
    import anthropic

    if isinstance(e, anthropic.AuthenticationError):
        return AIError("Claude rejected the API key", provider_down=True)
    if isinstance(e, anthropic.NotFoundError):
        return AIError(f"Claude model '{model}' wasn't found", provider_down=True)
    if isinstance(e, anthropic.RateLimitError):
        return AIError("Claude rate limit hit; try again in a moment", provider_down=True)
    if isinstance(e, anthropic.APIStatusError):
        text = str(e.message)
        if "credit balance" in text.lower():
            return AIError("The Anthropic account is out of credit (Plans & Billing)", provider_down=True)
        return AIError(f"Claude API error {e.status_code}: {text[:300]}", provider_down=not too_long(text))
    return AIError(f"Couldn't reach the Claude API: {e}", provider_down=True)


def _anthropic(cfg: dict, prompt: str, system: str | None, meter: pricing.Meter) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=cfg["anthropic_api_key"], timeout=600, max_retries=2)
    model = meter.model = model_for("anthropic", cfg)
    params = {"model": model, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}]}
    if system:
        params["system"] = system
    try:
        if model in _CLAUDE_FALLBACK_MODELS:
            # If a safety classifier declines, the API re-runs the request on a suitable model.
            msg = client.beta.messages.create(**params, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        else:
            msg = client.messages.create(**params)
    except anthropic.APIError as e:
        raise claude_error(e, model) from e
    claude_usage(msg, meter)
    if msg.stop_reason == "refusal":
        raise AIError("Claude declined this request")
    return "".join(b.text for b in msg.content if b.type == "text")


def _openai_compatible(base: str, key: str, model: str, prompt: str, system: str | None, pid: str,
                       meter: pricing.Meter) -> str:
    meter.model = model
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body: dict = {"model": model, "messages": messages}
    if pid == "openai":
        body["max_completion_tokens"] = MAX_TOKENS  # newer OpenAI models reject max_tokens / custom temperature
    elif pid == "deepseek":
        body["max_tokens"] = 8000
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = _post(f"{base}/chat/completions", json=body, headers=headers)
    try:
        data = r.json()
        openai_usage(data, meter)
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, ValueError) as e:
        raise AIError(f"Unexpected response from {base}") from e


def _gemini(cfg: dict, prompt: str, system: str | None, meter: pricing.Meter) -> str:
    model = meter.model = model_for("gemini", cfg)
    body: dict = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              json=body, headers={"x-goog-api-key": cfg["gemini_api_key"]})
    try:
        data = r.json()
        gemini_usage(data, meter)
        parts = data["candidates"][0]["content"]["parts"]
    except (KeyError, IndexError, ValueError) as e:
        raise AIError("Gemini returned no text (it may have blocked the request)") from e
    return "".join(p.get("text", "") for p in parts)


def gemini_usage(data: dict, meter: pricing.Meter) -> None:
    """Gemini's own API counts thinking apart from the answer; both are billed as output."""
    usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
    out, thoughts = _n(usage.get("candidatesTokenCount")), _n(usage.get("thoughtsTokenCount"))
    if out is not None or thoughts is not None:
        out = (out or 0) + (thoughts or 0)
    meter.add(_n(usage.get("promptTokenCount")), out, _n(usage.get("cachedContentTokenCount")) or 0,
              model=data.get("modelVersion"))


# ── Settings screen: model lists and connection tests ─────────────────

def providers() -> list[dict]:
    cfg = settings.section("ai")
    out = []
    for pid, info in PROVIDERS.items():
        ready, reason = configured(pid, cfg)
        out.append({"id": pid, "label": label(pid, cfg), "kind": info["kind"], "ready": ready, "reason": reason})
    return out


def list_models(pid: str) -> list[str]:
    cfg = settings.section("ai")
    if locked_out(pid, cfg):
        raise Locked(LOCKED_OUT, provider_down=True)
    if pid == "ollama":
        tags = _ollama_tags(cfg, fresh=True)
        if not tags:
            raise AIError(f"Ollama isn't reachable at {cfg['ollama_url']}", provider_down=True)
        return [m["name"] for m in tags if "embed" not in m["name"].lower()]
    if pid == "anthropic":
        import anthropic

        if not cfg["anthropic_api_key"]:
            raise AIError("Add an API key first", provider_down=True)
        try:
            return [m.id for m in anthropic.Anthropic(api_key=cfg["anthropic_api_key"], timeout=20).models.list()]
        except anthropic.APIError as e:
            raise AIError(f"Claude: {e}") from e
    if pid == "gemini":
        if not cfg["gemini_api_key"]:
            raise AIError("Add an API key first", provider_down=True)
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


def usage_report() -> dict:
    """Settings → AI: the one tally (core_ai_usage) in both its views. usage.summary(): this month and last, by purpose,
    model and day. pricing.summary(): the last 30 days by provider and by module, and the latest calls, with the names
    to show."""
    cfg = settings.section("ai")
    data = {**usage.summary(), **pricing.summary()}

    def provider(pid: str) -> str:
        return label(pid, cfg) if pid in PROVIDERS else pid

    def asker(mid: str) -> str:
        found = module.get(mid)
        return found.name if found else {"core": "Settings", "": "Outside a job"}.get(mid, mid)

    for row in data["last_30_days"]["by_provider"]:
        row["label"] = provider(row["id"])
    for row in data["last_30_days"]["by_module"]:
        row["label"] = asker(row["id"])
    for row in data["recent"]:
        row["provider_label"], row["module_label"] = provider(row["provider"]), asker(row["module"])
    return data


class _Probe(BaseModel):
    answer: str
    number: int


def test(pid: str, model: str = "") -> str:
    """A real structured round trip with a tiny schema: proves the key, the model and the way jobs will call it.
    model: one a job uses instead of the provider's own."""
    from . import ai_adapters

    cfg = with_models(settings.section("ai"), {pid: model})
    started = time.perf_counter()
    got = attempt(pid, cfg, "structured", lambda p, meter: ai_adapters.generate_structured(
        p, cfg, "Set answer to the word OK and number to 7.", "You answer in the JSON format you are given.", _Probe,
        None, meter), asker=("core", "test"))
    seconds = time.perf_counter() - started
    return (f"{label(pid, cfg)} · {model_for(pid, cfg)} answered in {seconds:.1f} s "
            f"({'structured output works' if got.number == 7 else 'it replied, but not exactly as asked'})")
