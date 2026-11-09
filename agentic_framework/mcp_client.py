
import asyncio
import json
import os

from dotenv import load_dotenv
from mcp import Client

# Load optional configuration from .env
load_dotenv()

MCP_URL = os.getenv(
    "DATA360_MCP_URL",
    "https://maimcpext.worldbank.org/ext/data360/mcp"
)


async def test_mcp_connection() -> None:
    """
    Connect to World Bank Data360, discover its tools,
    and test searching for a population indicator.
    """

    # 1. Establish the MCP connection
    async with Client(MCP_URL) as client:

        # 2. Discover tools advertised by the server
        response = await client.list_tools()

        print("Available MCP tools:")

        for tool in response.tools:
            print(f"- {tool.name}")

        # 3. Inspect the population-search tool's schema
        search_tool = next(
            (
                tool for tool in response.tools
                if tool.name == "data360_search_indicators"
            ),
            None
        )

        if search_tool is None:
            raise RuntimeError("Indicator search tool not found.")

        print("\nSearch tool input schema:")
        print(json.dumps(search_tool.input_schema, indent=2))

        # 4. Call the tool directly to test data discovery
        result = await client.call_tool(
            "data360_search_indicators",
            {"query": "total population"}
        )

        if result.is_error:
            raise RuntimeError(f"MCP tool error: {result.content}")

        # 5. Print a preview of the returned data
        data = (
            result.structured_content
            if result.structured_content is not None
            else [
                item.text
                for item in result.content
                if item.type == "text"
            ]
        )

        print("\nPopulation indicator search result:")
        print(str(data)[:3000])


if __name__ == "__main__":
    asyncio.run(test_mcp_connection())
