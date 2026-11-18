
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentic_framework import discovery


QUESTION = (
    "How did Egypt's population and life expectancy "
    "evolve between 2000 and 2023?"
)

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


def selection(requirement, indicator_id):
    return {
        "database_id": "WB_WDI",
        "indicator_id": indicator_id,
        "country_code": requirement["country_code"],
        "start_year": requirement["start_year"],
        "end_year": requirement["end_year"],
    }


def completion(content=None, tool_calls=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=content,
                    tool_calls=tool_calls or [],
                )
            )
        ]
    )


def search_call(query, call_id="call_1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(
            name="data360_search_indicators",
            arguments=json.dumps({
                "query": query,
                "required_country": "EGY",
                "limit": 5,
            }),
        ),
    )


def fake_client():
    tool = SimpleNamespace(
        name="data360_search_indicators",
        description="Search World Bank indicators",
        input_schema={"type": "object"},
    )
    return SimpleNamespace(
        list_tools=AsyncMock(
            return_value=SimpleNamespace(tools=[tool])
        )
    )


def search_result(indicator_id):
    return {
        "indicators": [
            {
                "database_id": "WB_WDI",
                "idno": indicator_id,
                "name": "Example indicator",
                "periodicity": "Annual",
                "time_period_range": "1960-2024",
                "covers_country": {"EGY": True},
            }
        ],
        "has_more": False,
        "next_offset": None,
    }


def install_responses(monkeypatch, responses):
    iterator = iter(responses)

    def fake_completion(messages, tools):
        return next(iterator)

    monkeypatch.setattr(
        discovery,
        "get_model_completion",
        fake_completion,
    )


@pytest.mark.parametrize(
    "content",
    [
        "",
        "{}",
        "[]",
        '{"database_id": "WB_WDI"}',
        '{"database_id": "WB-WDI", "indicator_id": "X", '
        '"country_code": "EGY", "start_year": 2000, '
        '"end_year": 2023}',
    ],
)
def test_invalid_selection_json(content):
    with pytest.raises((ValueError, json.JSONDecodeError)):
        discovery.parse_model_json(content)


def test_single_discovery_accepts_real_mcp_indicator(monkeypatch):
    expected = selection(POP, "WB_WDI_SP_POP_TOTL")

    install_responses(monkeypatch, [
        completion(tool_calls=[search_call("population")]),
        completion(content=json.dumps(expected)),
    ])

    mcp = AsyncMock(return_value=search_result(
        expected["indicator_id"]
    ))

    monkeypatch.setattr(
        discovery, "call_data360_tool", mcp
    )

    result = asyncio.run(
        discovery.discover_single_indicator(
            fake_client(), POP, QUESTION
        )
    )

    assert result["indicator_id"] == expected["indicator_id"]
    assert result["metric"] == POP["metric"]
    mcp.assert_awaited_once()


def test_search_recovers_after_no_matches(monkeypatch):
    expected = selection(LIFE, "WB_WDI_SP_DYN_LE00_IN")

    install_responses(monkeypatch, [
        completion(tool_calls=[
            search_call("life expectancy total", "call_1")
        ]),
        completion(tool_calls=[
            search_call("life expectancy at birth", "call_2")
        ]),
        completion(content=json.dumps(expected)),
    ])

    mcp = AsyncMock(side_effect=[
        RuntimeError(
            "World Bank error: No indicators found"
        ),
        search_result(expected["indicator_id"]),
    ])
    monkeypatch.setattr(
        discovery, "call_data360_tool", mcp
    )

    result = asyncio.run(
        discovery.discover_single_indicator(
            fake_client(), LIFE, QUESTION
        )
    )

    assert result["indicator_id"] == expected["indicator_id"]
    assert mcp.await_count == 2


def test_rejects_unseen_indicator_then_recovers(monkeypatch):
    expected = selection(POP, "WB_WDI_SP_POP_TOTL")

    invented = {
        **expected,
        "indicator_id": "WB_WDI_FAKE",
    }

    install_responses(monkeypatch, [
        completion(tool_calls=[search_call("population")]),
        completion(content=json.dumps(invented)),
        completion(content=json.dumps(expected)),
    ])

    monkeypatch.setattr(
        discovery,
        "call_data360_tool",
        AsyncMock(return_value=search_result(
            expected["indicator_id"]
        )),
    )

    result = asyncio.run(
        discovery.discover_single_indicator(
            fake_client(), POP, QUESTION
        )
    )

    assert result["indicator_id"] == expected["indicator_id"]


def test_rejects_changed_year_range_then_recovers(monkeypatch):
    expected = selection(LIFE, "WB_WDI_SP_DYN_LE00_IN")

    shortened = {
        **expected,
        "end_year": 2020,
    }

    install_responses(monkeypatch, [
        completion(tool_calls=[
            search_call("life expectancy")
        ]),
        completion(content=json.dumps(shortened)),
        completion(content=json.dumps(expected)),
    ])

    monkeypatch.setattr(
        discovery,
        "call_data360_tool",
        AsyncMock(return_value=search_result(
            expected["indicator_id"]
        )),
    )

    result = asyncio.run(
        discovery.discover_single_indicator(
            fake_client(), LIFE, QUESTION
        )
    )

    assert result["end_year"] == 2023


def test_two_requirements_trigger_two_discoveries(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "decompose_question",
        lambda question: [POP, LIFE],
    )

    calls = []

    async def fake_single(client, requirement, question):
        calls.append(requirement["metric"])

        indicator_id = (
            "WB_WDI_SP_POP_TOTL"
            if requirement["metric"] == POP["metric"]
            else "WB_WDI_SP_DYN_LE00_IN"
        )

        return {
            **selection(requirement, indicator_id),
            "metric": requirement["metric"],
        }

    monkeypatch.setattr(
        discovery,
        "discover_single_indicator",
        fake_single,
    )

    result = asyncio.run(
        discovery.discover_indicators(None, QUESTION)
    )

    assert len(result) == 2
    assert calls == [POP["metric"], LIFE["metric"]]
    assert len({
        item["indicator_id"] for item in result
    }) == 2


def test_duplicate_datasets_are_not_selected_twice(monkeypatch):
    monkeypatch.setattr(
        discovery,
        "decompose_question",
        lambda question: [POP, POP],
    )

    async def fake_single(client, requirement, question):
        return {
            **selection(
                requirement, "WB_WDI_SP_POP_TOTL"
            ),
            "metric": requirement["metric"],
        }

    monkeypatch.setattr(
        discovery,
        "discover_single_indicator",
        fake_single,
    )

    result = asyncio.run(
        discovery.discover_indicators(None, QUESTION)
    )

    assert len(result) == 1


def test_unexpected_mcp_error_propagates(monkeypatch):
    install_responses(monkeypatch, [
        completion(tool_calls=[search_call("population")]),
    ])

    monkeypatch.setattr(
        discovery,
        "call_data360_tool",
        AsyncMock(side_effect=RuntimeError(
            "MCP connection failed"
        )),
    )

    with pytest.raises(
        RuntimeError, match="MCP connection failed"
    ):
        asyncio.run(
            discovery.discover_single_indicator(
                fake_client(), POP, QUESTION
            )
        )
