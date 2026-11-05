"""The family's model table: what it recommends, how it ranks what is installed, and that an unlisted model still works."""
import pytest

from core.server import ai, model_catalog


def test_the_recommendations_are_listed_families():
    for tier in ("big", "small"):
        assert model_catalog.family_of(model_catalog.recommended(tier))["status"] == "recommended"


def test_the_table_has_no_repeats_and_replacements_exist():
    names = [f["family"] for f in model_catalog.FAMILIES]
    assert len(names) == len(set(names))
    for f in model_catalog.FAMILIES:
        assert f["status"] in ("recommended", "current", "legacy")
        if f.get("superseded_by"):
            assert f["superseded_by"] in names


@pytest.mark.parametrize("name, family", [("qwen3.5:9b", "qwen3.5"), ("qwen3:8b", "qwen3"), ("qwen2.5:7b-instruct-q4_K_M", "qwen2.5"),
                                           ("Llama3.1:8b", "llama3.1"), ("llama3.1", "llama3.1")])
def test_a_name_finds_its_family_exactly(name, family):
    assert model_catalog.family_of(name)["family"] == family


def test_qwen3_is_not_mistaken_for_qwen3_5():
    assert model_catalog.rank("qwen3.5:9b") < model_catalog.rank("qwen3:8b") < model_catalog.rank("qwen2.5:7b")


def test_unlisted_models_rank_after_listed_ones_and_are_still_usable():
    assert model_catalog.family_of("some-new-model:7b") is None
    assert model_catalog.rank("some-new-model:7b") > model_catalog.rank("llama3:8b")
    tags = [{"name": "some-new-model:7b", "details": {"parameter_size": "7B"}}]
    assert ai.preferred_ollama_model(tags) == "some-new-model:7b"


def test_the_newest_installed_family_is_used(monkeypatch):
    tags = [{"name": "qwen2.5:7b", "details": {"parameter_size": "7B"}}, {"name": "qwen3.5:9b", "details": {"parameter_size": "9B"}},
            {"name": "qwen3:8b", "details": {"parameter_size": "8B"}}, {"name": "nomic-embed-text:latest", "details": {"parameter_size": "137M"}}]
    assert ai.preferred_ollama_model(tags) == "qwen3.5:9b"
    assert ai.preferred_ollama_model([t for t in tags if t["name"] != "qwen3.5:9b"]) == "qwen3:8b"


def test_replacements_are_reported():
    assert model_catalog.superseded_by("qwen2.5:7b") == "qwen3.5"
    assert model_catalog.superseded_by("qwen3.5:9b") is None and model_catalog.superseded_by("unknown:1b") is None


def test_only_thinking_models_are_told_not_to_think():
    assert model_catalog.can_think("qwen3.5:9b") and model_catalog.can_think("qwen3:8b")
    assert not model_catalog.can_think("qwen2.5:7b") and not model_catalog.can_think("unknown:1b")
