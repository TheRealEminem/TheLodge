"""Turning a Pydantic model into the JSON schema a provider accepts, and a model's reply back into the model.

Providers differ. Claude compiles the schema into a grammar and refuses a large one ("Schema is too complex")
when optional or nullable fields multiply it, so it gets a *flat* variant: every field required, "" instead of
null. Ollama and OpenAI-compatible servers get a plain portable schema. In both cases blank_to_none maps ""
back to None before the reply is validated.
"""
import copy
import json
import re
from typing import Any, get_args

from pydantic import BaseModel

# Schema metadata to strip. Only applied to schema nodes, never to the names inside "properties"
# (a field may well be called "title").
_DROP_KEYS = {"title", "default"}


def portable_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A plain JSON schema most providers accept.

    - `$ref`/`$defs` are inlined.
    - Optional fields (`anyOf: [X, null]`) become plain X and are dropped from `required`, so the model simply
      omits them when unknown.
    - `title`/`default` metadata is removed.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node: Any) -> tuple[Any, bool]:
        """Returns (schema, optional)."""
        if isinstance(node, list):
            return [walk(n)[0] for n in node], False
        if not isinstance(node, dict):
            return node, False
        if "$ref" in node:
            return walk(copy.deepcopy(defs[node["$ref"].split("/")[-1]]))
        if "anyOf" in node:
            options = [o for o in node["anyOf"] if o.get("type") != "null"]
            if len(options) < len(node["anyOf"]) and len(options) == 1:
                inner, _ = walk(options[0])
                extra = {k: v for k, v in node.items() if k not in _DROP_KEYS and k != "anyOf"}
                return {**inner, **extra}, True
        out: dict[str, Any] = {}
        optional_props: set[str] = set()
        for key, value in node.items():
            if key in _DROP_KEYS:
                continue
            if key == "properties":
                props = {}
                for name, sub in value.items():
                    props[name], is_optional = walk(sub)
                    if is_optional:
                        optional_props.add(name)
                out[key] = props
            else:
                out[key] = walk(value)[0]
        if "required" in out:
            out["required"] = [r for r in out["required"] if r not in optional_props]
        return out, False

    return walk(raw)[0]


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Flat schema for grammar-constrained decoding: every property required, no nulls, additionalProperties
    false. Unknown strings come back as ""."""
    schema = portable_schema(model)

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["required"] = list(node["properties"])
                node["additionalProperties"] = False
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


def parse_json_text(text: str) -> Any:
    """Parse JSON from a model reply, tolerating ```json fences or surrounding prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _inner_model(tp: Any) -> type[BaseModel] | None:
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return tp
    for arg in get_args(tp):
        if found := _inner_model(arg):
            return found
    return None


def blank_to_none(model: type[BaseModel], data: Any) -> Any:
    """Map "" back to None for optional fields (recursing into nested models)."""
    if not isinstance(data, dict):
        return data
    out = dict(data)
    for name, field in model.model_fields.items():
        if name not in out:
            continue
        value = out[name]
        if value == "" and not field.is_required() and field.default is None:
            out[name] = None
        elif sub := _inner_model(field.annotation):
            if isinstance(value, list):
                out[name] = [blank_to_none(sub, v) for v in value]
            elif isinstance(value, dict):
                out[name] = blank_to_none(sub, value)
    return out
