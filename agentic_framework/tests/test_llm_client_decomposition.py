


import pytest

from agentic_framework import llm_client
import json

POP = {
    "metric": "total population",
    "country_code": "EGY",
    "start_year": 2000,
    "end_year": 2023,
}

LIFE = {
    "metric": "life expectancy at birth, total (years)",
    "country_code": "EGY",
    "start_year": 2000,
    "end_year": 2023,
}


def respond(monkeypatch, payload):
    monkeypatch.setattr(
        llm_client,
        "get_model_response",
        lambda prompt: payload,
    )


def test_decompose_one_indicator(monkeypatch):
    respond(monkeypatch, json.dumps([POP]))

    assert llm_client.decompose_question(
        "Egypt's population from 2000 to 2023"
    ) == [POP]


def test_decompose_two_indicators(monkeypatch):
    respond(monkeypatch, json.dumps([POP, LIFE]))

    assert llm_client.decompose_question(
        "Compare Egypt's population and life expectancy"
    ) == [POP, LIFE]


def test_decompose_removes_duplicates(monkeypatch):
    respond(monkeypatch, json.dumps([POP, POP]))

    assert llm_client.decompose_question(
        "Population change in Egypt"
    ) == [POP]


@pytest.mark.parametrize(
    "payload",
    [
        "{}",
        "not json",
        "[]",
        json.dumps([{"metric": "population"}]),
        json.dumps([{**POP, "country_code": "Egypt"}]),
        json.dumps([{**POP, "start_year": 2025,
                     "end_year": 2020}]),
        json.dumps([{**POP, "start_year": True}]),
        json.dumps([{**POP, "metric": ""}]),
        json.dumps([POP] * 6),
    ],
)
def test_invalid_decompositions(monkeypatch, payload):
    respond(monkeypatch, payload)

    with pytest.raises(ValueError):
        llm_client.decompose_question("Example question")


def test_decomposition_preserves_qualifier(monkeypatch):
    qualified = {
        "metric": (
            "unemployment, total, modeled ILO estimate "
            "(% of total labor force)"
        ),
        "country_code": "CHE",
        "start_year": 2010,
        "end_year": 2023,
    }

    respond(monkeypatch, json.dumps([qualified]))

    result = llm_client.decompose_question(
        "Swiss modeled ILO unemployment, 2010-2023"
    )

    assert result[0]["metric"] == qualified["metric"]


def test_decomposition_uses_original_question(monkeypatch):
    captured = {}

    def fake_model(prompt):
        captured["prompt"] = prompt
        return json.dumps([POP])

    monkeypatch.setattr(
        llm_client,
        "get_model_response",
        fake_model,
    )

    question = "Egypt's total population between 2000 and 2023"

    llm_client.decompose_question(question)

    assert question in captured["prompt"]
