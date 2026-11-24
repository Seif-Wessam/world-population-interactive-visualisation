import asyncio
import os
import re
from decimal import Decimal
from time import perf_counter

import pandas as pd
import pytest


DATABASE = "WB_WDI"
INDICATOR = "WB_WDI_SP_POP_TOTL"
COUNTRY = "EGY"
START_YEAR = 2000
END_YEAR = 2023

RESULT_COLUMNS = [
    "population_2000",
    "population_2023",
    "absolute_change",
    "percentage_change",
]


async def fetch_reference_values():
    """Fetch known endpoint observations without model discovery."""
    from mcp import Client
    from agentic_framework.mcp_client import (
        MCP_URL,
        call_data360_tool,
    )

    values = {}

    async with Client(MCP_URL) as client:
        for year in (START_YEAR, END_YEAR):
            payload = await call_data360_tool(
                client,
                "data360_get_data",
                {
                    "database_id": DATABASE,
                    "indicator_id": INDICATOR,
                    "country_code": COUNTRY,
                    "start_year": year,
                    "end_year": year,
                    "limit": 100,
                    "offset": 0,
                    "ref_area_filter": "none",
                },
            )

            assert payload.get("has_more") is False, (
                f"Reference response for {year} is incomplete "
                "or lacks pagination confirmation."
            )

            metadata = payload.get("metadata") or {}
            assert metadata.get("idno") == INDICATOR, (
                "Reference response has an unexpected indicator."
            )

            records = payload.get("data")
            assert isinstance(records, list)
            assert len(records) == 1, (
                f"Expected exactly one reference observation "
                f"for {year}; received {len(records)}."
            )

            record = records[0]
            assert record["REF_AREA"] == COUNTRY
            assert Decimal(str(record["TIME_PERIOD"])) == year
            assert Decimal(str(record["UNIT_MULT"])) == 0
            assert record["OBS_VALUE"] is not None

            value = Decimal(str(record["OBS_VALUE"]))
            assert value.is_finite()
            assert value > 0
            assert value == value.to_integral_value()

            values[year] = value

    start = values[START_YEAR]
    end = values[END_YEAR]
    change = end - start

    return {
        "population_2000": start,
        "population_2023": end,
        "absolute_change": change,
        "percentage_change": change * Decimal(100) / start,
    }


def answer_numbers(answer):
    """Extract ordinary numbers, allowing comma-separated thousands."""
    tokens = re.findall(
        r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])",
        answer,
    )
    return {
        Decimal(token.replace(",", ""))
        for token in tokens
    }


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_ANSWER_TEST") != "1",
    reason="Opt-in test requiring real Qwen and MCP access.",
)
def test_live_answer(monkeypatch):
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    # Import only when live testing is enabled.
    from agentic_framework.main import answer_question

    question = (
        "How did Egypt's total population change between "
        "2000 and 2023?"
       "Report the population in both years, the absolute "
        "change in people, and the percentage change. "
        "Return the numerical summary as one row with columns "
        "population_2000, population_2023, absolute_change, "
        "and percentage_change. "
        "In the explanation, report the population counts and "
        "absolute change as whole people, and the percentage "
        "change to two decimal places."
    )

    async def run_case():
        # Establish expected values before invoking the agent.
        expected = await fetch_reference_values()

        started = perf_counter()
        outcome = await answer_question(question)
        elapsed = perf_counter() - started

        return expected, outcome, elapsed

    expected, outcome, elapsed = asyncio.run(run_case())
    results = outcome.get("results")

    # Diagnostics remain useful even for failed/partial outcomes.
    print(f"\nAgent elapsed: {elapsed:.1f} seconds")
    print("\nWorld Bank reference:", expected)
    print("\nSelected datasets:", outcome.get("selections"))
    print("\nSQL:\n", outcome.get("sql"))
    print(
        "\nResults:\n",
        results.to_string(index=False)
        if isinstance(results, pd.DataFrame)
        else results,
    )
    print("\nStatus:", outcome.get("analysis_status"))
    print("Reason:", outcome.get("analysis_reason"))
    print("\nAnswer:\n", outcome.get("answer"))

    assert outcome["s3_prefixes"] == []

    selections = outcome["selections"]
    assert len(selections) == 1

    selection = selections[0]
    for key, value in {
        "database_id": DATABASE,
        "indicator_id": INDICATOR,
        "country_code": COUNTRY,
        "start_year": START_YEAR,
        "end_year": END_YEAR,
    }.items():
        assert selection[key] == value

    assert isinstance(outcome["sql"], str)
    assert outcome["sql"].strip()
    assert isinstance(results, pd.DataFrame)
    assert len(results) == 1
    assert results.columns.is_unique
    assert set(results.columns) == set(RESULT_COLUMNS)

    row = results.iloc[0]

    # Compare whole-person values exactly.
    for column in RESULT_COLUMNS[:3]:
        assert pd.notna(row[column])
        actual = Decimal(str(row[column]))
        assert actual == expected[column], (
            f"{column}: got {actual}, "
            f"World Bank reference implies {expected[column]}"
        )

    # Allow SQL to round to two decimal places.
    actual_percentage = Decimal(str(row["percentage_change"]))
    assert actual_percentage.is_finite()
    assert abs(
        actual_percentage - expected["percentage_change"]
    ) <= Decimal("0.005")

    assert outcome["analysis_status"] == "complete", (
        f"Analysis remained incomplete: "
        f"{outcome.get('analysis_reason')}"
    )
    assert outcome["analysis_reason"] is None

    answer = outcome["answer"]
    assert isinstance(answer, str)
    assert answer.strip()
    assert "{{" not in answer
    assert "}}" not in answer

    # Check that the requested figures appear in the prose.
    numbers = answer_numbers(answer)

    for value in (
        Decimal(START_YEAR),
        Decimal(END_YEAR),
        expected["population_2000"],
        expected["population_2023"],
        expected["absolute_change"],
    ):
        assert value in numbers, (
            f"Expected figure {value} is absent from the answer."
        )

    rounded_percentage = expected["percentage_change"].quantize(
        Decimal("0.01")
    )
    assert rounded_percentage in numbers, (
        f"Expected percentage {rounded_percentage} "
        "is absent from the answer."
    )