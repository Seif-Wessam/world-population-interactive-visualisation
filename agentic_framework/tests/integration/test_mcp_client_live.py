
import asyncio
import math

from mcp import Client

from agentic_framework.mcp_client import (
    MCP_URL,
    call_data360_tool,
    fetch_all_observations,
)


async def check_live_mcp():
    # Verify that we can retrieve a known indicator from the MCP and its metadata.
    indicator_id = "WB_WDI_NY_GDP_PCAP_CD"

    async with Client(MCP_URL) as client:

        # Retrieve the complete requested series.
        observations = await fetch_all_observations(
            client,
            database_id="WB_WDI",
            indicator_id=indicator_id,
            country_code="CHE",
            start_year=2015,
            end_year=2023,
        )

        # Retrieve full metadata independently.
        metadata = await call_data360_tool(
            client,
            "data360_get_metadata",
            {
                "database_id": "WB_WDI",
                "indicator_id": indicator_id,
                "required_country": "CHE",
            },
        )

    records = observations["data"]

    # Verify the requested series.
    assert observations["count"] == 9
    assert observations["has_more"] is False

    assert {
        int(record["TIME_PERIOD"])
        for record in records
    } == set(range(2015, 2024))

    assert all(
        record["REF_AREA"] == "CHE"
        for record in records
    )

    assert all(
        math.isfinite(float(record["OBS_VALUE"]))
        for record in records
    )

    # Verify metadata identifies the same indicator.
    indicator_metadata = metadata["indicator_metadata"]

    assert indicator_metadata["idno"] == indicator_id
    assert indicator_metadata["database_id"] == "WB_WDI"

    # Verify we preserved the raw MCP pages.
    assert len(observations["raw_pages"]) >= 1

    print("Live MCP integration test passed.")
    print("Observations:", observations["count"])
    print("Pages:", len(observations["raw_pages"]))
    print("Indicator:", indicator_metadata["name"])
    print("Unit:", indicator_metadata["measurement_unit"])


def test_live_mcp():
    asyncio.run(check_live_mcp())

def test_live_pagination():
    # Verify that we can retrieve more than one page of observations from the MCP.
    async def run():

        async with Client(MCP_URL) as client:
            return await fetch_all_observations(
                client,
                database_id="WB_WDI",
                indicator_id="WB_WDI_NY_GDP_PCAP_CD",
                country_code="CHE;FRA;USA",
                start_year=1980,
                end_year=2024,
            )

    result = asyncio.run(run())

    records = result["data"]
    pages = result["raw_pages"]

    # 1. Ensure we actually exceeded one page.
    assert len(records) > 100

    # 2. Ensure multiple MCP pages were retrieved.
    assert len(pages) >= 2

    # 3. Verify all pages were combined.
    assert len(records) == sum(
        len(page["data"]) for page in pages
    )

    # 4. Verify the final page indicates completion.
    assert pages[-1]["has_more"] is False
    assert result["has_more"] is False

    # 5. Verify the requested scope was respected.
    assert all(
        record["REF_AREA"] in {"CHE", "FRA", "USA"}
        and 1980 <= int(record["TIME_PERIOD"]) <= 2024
        for record in records
    )

    # 6. Detect duplicated observations across pages.
    keys = [
        (record["REF_AREA"], record["TIME_PERIOD"])
        for record in records
    ]

    assert len(keys) == len(set(keys))

    print("Pagination test passed.")
    print("Total observations:", len(records))
    print("Pages retrieved:", len(pages))
    print("Records per page:", [
        len(page["data"]) for page in pages
    ])