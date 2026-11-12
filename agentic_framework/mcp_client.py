import asyncio
import json
import os

from dotenv import load_dotenv
from mcp import Client


load_dotenv()

MCP_URL = os.getenv(
    "DATA360_MCP_URL",
    "https://maimcpext.worldbank.org/ext/data360/mcp",
)

# Tools our application permits Qwen to request.
ALLOWED_TOOLS = {
    "data360_search_indicators",
    "data360_get_metadata",
    "data360_get_disaggregation",
    "data360_get_data",
}


def parse_tool_result(result) -> dict:
    """Convert an MCP tool response into a Python dictionary."""

    if result.is_error:
        raise RuntimeError(f"MCP tool failed: {result.content}")

    if result.structured_content is not None:
        data = result.structured_content
    else:
        text_blocks = [
            item.text
            for item in result.content
            if item.type == "text"
        ]

        if len(text_blocks) != 1:
            raise ValueError("Unexpected MCP response format.")

        data = json.loads(text_blocks[0])

    if not isinstance(data, dict):
        raise ValueError("Expected an MCP response dictionary.")

    if data.get("error"):
        raise RuntimeError(f"World Bank error: {data['error']}")

    return data


async def call_data360_tool(
    client: Client,
    tool_name: str,
    arguments: dict,
) -> dict:
    """Execute a permitted World Bank MCP tool."""

    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"Unauthorized MCP tool: {tool_name}")

    if not isinstance(arguments, dict):
        raise TypeError("Tool arguments must be a dictionary.")

    result = await client.call_tool(
        tool_name,
        arguments,
    )

    return parse_tool_result(result)


async def fetch_all_observations(
    client: Client,
    database_id: str,
    indicator_id: str,
    country_code: str,
    start_year: int,
    end_year: int,
) -> dict:
    """Retrieve every page for one country and indicator."""

    all_records = []
    raw_pages = []
    offset = 0

    # Temporary safety limit for our first integration.
    max_pages = 100

    for _ in range(max_pages):

        page = await call_data360_tool(
            client,
            "data360_get_data",
            {
                "database_id": database_id,
                "indicator_id": indicator_id,
                "country_code": country_code,
                "start_year": start_year,
                "end_year": end_year,
                "limit": 100,
                "offset": offset,
                "ref_area_filter": "none",
            },
        )

        records = page.get("data")

        if not isinstance(records, list):
            raise ValueError("Unexpected observation format.")

        raw_pages.append(page)
        all_records.extend(records)

        if not page.get("has_more", False):
            return {
                "data": all_records,
                "count": len(all_records),
                "has_more": False,
                "metadata": raw_pages[0].get("metadata"),
                "raw_pages": raw_pages,
            }

        next_offset = page.get("next_offset")

        if not isinstance(next_offset, int) or next_offset <= offset:
            raise ValueError("Invalid MCP pagination information.")

        offset = next_offset

    raise RuntimeError("Maximum MCP page limit exceeded.")


async def test_mcp_connection() -> None:
    """Check MCP connectivity and discover advertised tools."""

    async with Client(MCP_URL) as client:

        response = await client.list_tools()

        available = {
            tool.name
            for tool in response.tools
        }

        print("Available permitted tools:")

        for name in sorted(available & ALLOWED_TOOLS):
            print(f"- {name}")

        if "data360_search_indicators" not in available:
            raise RuntimeError("Indicator search tool unavailable.")


if __name__ == "__main__":
    asyncio.run(test_mcp_connection())
