"""Live integration test for two-indicator World Bank analytics.

Run explicitly with RUN_MULTI_INDICATOR_TESTS=1.
Ordinary pytest runs skip this test to avoid API charges and network calls.
"""

import asyncio
import os

import pandas as pd
import pytest
from mcp import Client

from agentic_framework.main import answer_question
from agentic_framework.mcp_client import MCP_URL, call_data360_tool


QUESTION = (
    "For Egypt, retrieve annual total population and life expectancy "
    "at birth, total (years), from 2000 through 2023. "
    "Return one row per year with columns year, population, "
    "and life_expectancy, ordered by year ascending."
)

COUNTRY = "EGY"
START_YEAR = 2000
END_YEAR = 2023
INDICATORS = {
    "population": "WB_WDI_SP_POP_TOTL",
    "life_expectancy": "WB_WDI_SP_DYN_LE00_IN",
}


async def fetch_reference_series(client, indicator_id: str) -> pd.DataFrame:
    """Fetch all pages independently of the agent's retrieval code."""
    records = []
    offset = 0

    for _ in range(100):
        page = await call_data360_tool(
            client,
            "data360_get_data",
            {
                "database_id": "WB_WDI",
                "indicator_id": indicator_id,
                "country_code": COUNTRY,
                "start_year": START_YEAR,
                "end_year": END_YEAR,
                "limit": 100,
                "offset": offset,
                "ref_area_filter": "none",
            },
        )

        records.extend(page["data"])

        if not page.get("has_more", False):
            break

        next_offset = page.get("next_offset")
        assert isinstance(next_offset, int) and next_offset > offset, (
            f"Invalid pagination for {indicator_id}: {next_offset}"
        )
        offset = next_offset
    else:
            pytest.fail(f"Reference pagination did not finish for {indicator_id}")

    assert records, f"No reference observations for {indicator_id}"
    raw = pd.DataFrame(records)

    assert raw["REF_AREA"].eq(COUNTRY).all()
    if "INDICATOR" in raw:
        assert raw["INDICATOR"].eq(indicator_id).all()
    if "UNIT_MULT" in raw:
        multiplier = pd.to_numeric(raw["UNIT_MULT"], errors="raise")
        assert multiplier.notna().all() and multiplier.eq(0).all(), (
            "The independent reference requires the currently supported "
            f"unit multiplier of zero: {indicator_id}"
        )

    reference = pd.DataFrame({
        "year": pd.to_numeric(raw["TIME_PERIOD"], errors="raise").astype(int),
        "value": pd.to_numeric(raw["OBS_VALUE"], errors="raise"),
    })
    assert reference["year"].between(START_YEAR, END_YEAR).all()
    assert not reference["year"].duplicated().any()
    return reference.sort_values("year").reset_index(drop=True)


async def independent_reference() -> pd.DataFrame:
    """Construct expected wide-form results directly from MCP observations."""
    async with Client(MCP_URL) as client:
        population = await fetch_reference_series(client, INDICATORS["population"])
        life = await fetch_reference_series(client, INDICATORS["life_expectancy"])

    expected_years = list(range(START_YEAR, END_YEAR + 1))
    for name, series in (("population", population), ("life_expectancy", life)):
        assert series["year"].tolist() == expected_years, (
            f"{name} does not cover every requested year; "
            f"actual years: {series['year'].tolist()}"
        )

    combined = population.rename(columns={"value": "population"}).merge(
        life.rename(columns={"value": "life_expectancy"}),
        on="year",
        how="outer",
        validate="one_to_one",
        indicator=True,
    )
    assert combined["_merge"].eq("both").all()
    return (
        combined.drop(columns="_merge")
        .sort_values("year")
        .reset_index(drop=True)
    )


def canonical_result(result: pd.DataFrame) -> pd.DataFrame:
    assert isinstance(result, pd.DataFrame)
    assert list(result.columns) == ["year", "population", "life_expectancy"], (
        f"Unexpected SQL output columns: {list(result.columns)}"
    )
    actual = result.copy()
    assert actual.notna().all().all(), "SQL result contains missing values"
    actual["year"] = pd.to_numeric(actual["year"], errors="raise").astype(int)
    for column in ("population", "life_expectancy"):
        actual[column] = pd.to_numeric(actual[column], errors="raise")
    assert not actual["year"].duplicated().any()
    return actual.sort_values("year").reset_index(drop=True)


@pytest.mark.skipif(
    os.getenv("RUN_MULTI_INDICATOR_TESTS") != "1",
    reason="Live Qwen + MCP integration requires explicit opt-in",
)
def test_two_indicator_pipeline(monkeypatch):
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    # A reference obtained independently of the agent's retrieval path.
    expected = asyncio.run(independent_reference())

    # Real decomposition, indicator discovery, MCP retrieval, normalization,
    # DuckDB, Qwen SQL generation, SQL guard and execution.
    outcome = asyncio.run(answer_question(QUESTION))

    selections = outcome["selections"]
    assert len(selections) == 2, f"Expected two selections, got {selections}"

    by_id = {item["indicator_id"]: item for item in selections}
    assert set(by_id) == set(INDICATORS.values()), (
        f"Unexpected indicators selected: {list(by_id)}"
    )
    for selected in selections:
        assert selected["database_id"] == "WB_WDI"
        assert selected["country_code"] == COUNTRY
        assert selected["start_year"] == START_YEAR
        assert selected["end_year"] == END_YEAR

    assert outcome["s3_prefixes"] == []
    assert {item["indicator_id"] for item in outcome["metadata"]} == (
        set(INDICATORS.values())
    )

    actual = canonical_result(outcome["results"])
    assert actual["year"].tolist() == list(range(START_YEAR, END_YEAR + 1))

    pd.testing.assert_frame_equal(
        actual,
        expected,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-6,
    )

    print("\nLIVE MULTI-INDICATOR INTEGRATION PASSED")
    print("Selections:", selections)
    print("SQL:\n", outcome["sql"])
    print("Rows:", len(actual))
    print(actual.to_string(index=False))