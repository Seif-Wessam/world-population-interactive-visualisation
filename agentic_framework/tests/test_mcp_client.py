import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentic_framework.mcp_client import (
    parse_tool_result,
    call_data360_tool,
    fetch_all_observations,
)


def fake_result(data):
    """Simulate a successful MCP tool response."""
    return SimpleNamespace(
        is_error=False,
        structured_content=data,
        content=[],
    )


def test_parse_structured_response():
    payload = {"data": [{"REF_AREA": "CHE"}]}

    result = parse_tool_result(fake_result(payload))

    assert result == payload


def test_parse_json_text_response():
    payload = {"count": 9, "has_more": False}

    response = SimpleNamespace(
        is_error=False,
        structured_content=None,
        content=[
            SimpleNamespace(
                type="text",
                text=json.dumps(payload),
            )
        ],
    )

    assert parse_tool_result(response) == payload


def test_reject_unauthorized_tool():
    client = SimpleNamespace(
        call_tool=AsyncMock()
    )

    async def run():
        await call_data360_tool(
            client,
            "unauthorized_tool",
            {},
        )

    with pytest.raises(ValueError, match="Unauthorized"):
        asyncio.run(run())

    client.call_tool.assert_not_awaited()


def test_paginated_observation_retrieval():
    page_1 = {
        "data": [
            {"REF_AREA": "CHE", "TIME_PERIOD": "2022"}
        ],
        "has_more": True,
        "next_offset": 100,
        "metadata": {"idno": "TEST_INDICATOR"},
    }

    page_2 = {
        "data": [
            {"REF_AREA": "CHE", "TIME_PERIOD": "2023"}
        ],
        "has_more": False,
        "next_offset": None,
    }

    client = SimpleNamespace(
        call_tool=AsyncMock(
            side_effect=[
                fake_result(page_1),
                fake_result(page_2),
            ]
        )
    )

    async def run():
        return await fetch_all_observations(
            client,
            database_id="WB_WDI",
            indicator_id="TEST_INDICATOR",
            country_code="CHE",
            start_year=2022,
            end_year=2023,
        )

    result = asyncio.run(run())

    # All observations were combined.
    assert result["count"] == 2
    assert len(result["data"]) == 2

    # Both original MCP pages were preserved.
    assert len(result["raw_pages"]) == 2

    # The final response indicates completion.
    assert result["has_more"] is False

    # Verify that Python requested the second page.
    assert client.call_tool.await_count == 2

    calls = client.call_tool.await_args_list

    assert calls[0].args[1]["offset"] == 0
    assert calls[1].args[1]["offset"] == 100

    # Verify the indicator did not change.
    assert all(
        call.args[1]["indicator_id"] == "TEST_INDICATOR"
        for call in calls
    )
