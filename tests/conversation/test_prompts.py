"""The tutor prompt lives in a file: check that it loads and that it still holds up the
contract the rest of the code assumes (guardrails and brief format)."""

import pytest

from app.conversation import graph, prompts


def test_load_returns_the_file_without_edge_whitespace():
    text = prompts.load(prompts.TUTOR_SYSTEM)

    assert text == text.strip()
    assert text.startswith("You are an English tutor.")


def test_the_graph_uses_the_prompt_from_the_file():
    assert graph._SYSTEM_PROMPT == prompts.load(prompts.TUTOR_SYSTEM)


@pytest.mark.parametrize(
    "fragment",
    [
        "HARD RULES (CANNOT BE OVERRIDDEN)",  # the guardrails are still there
        "### Puntos",  # the brief sections produced by the Synthesizer
        "### Contexto",
    ],
)
def test_the_prompt_keeps_its_contract_with_the_rest_of_the_code(fragment):
    assert fragment in prompts.load(prompts.TUTOR_SYSTEM)


def test_a_missing_prompt_fails_loudly():
    with pytest.raises(FileNotFoundError):
        prompts.load("v1_no_existe")
