
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from agentic_framework import main


POP = {
    "metric": "total population",
    "database_id": "WB_WDI",
    "indicator_id": "WB_WDI_SP_POP_TOTL",
    "country_code": "EGY",
    "start_year": 2022,
    "end_year": 2023,
}

LIFE = {
    "metric": "life expectancy at birth, total",
    "database_id": "WB_WDI",
    "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
    "country_code": "EGY",
    "start_year": 2022,
    "end_year": 2023,
}


def observations(selection):
    values = (
        [110_000_000.0, 112_000_000.0]
        if selection["indicator_id"] == POP["indicator_id"]
        else [70.0, 71.0]
    )

    return pd.DataFrame({
        "indicator_id": [selection["indicator_id"]] * 2,
        "country_iso3": ["EGY", "EGY"],
        "year": [2022, 2023],
        "value": values,
    })


def metadata(selection):
    return pd.DataFrame([{
        "indicator_id": selection["indicator_id"],
        "database_id": "WB_WDI",
        "name": selection["metric"],
        "unit": "Example unit",
        "definition": "Test indicator",
        "periodicity": "Annual",
    }])


class FakeMCPClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def configure_pipeline(monkeypatch, selections):
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    # No network connections are permitted in these tests.
    monkeypatch.setattr(main, "Client", FakeMCPClient)

    async def fake_discovery(client, question):
        return selections

    retrieval = AsyncMock(
        side_effect=lambda client, selection: (
            {"selection": selection},
            {"selection": selection},
        )
    )

    monkeypatch.setattr(
        main, "discover_indicators", fake_discovery
    )
    monkeypatch.setattr(
        main, "retrieve_dataset", retrieval
    )

    monkeypatch.setattr(
        main,
        "normalize_observations",
        lambda raw, indicator_id: observations(
            raw["selection"]
        ),
    )
    monkeypatch.setattr(
        main,
        "normalize_metadata",
        lambda raw: metadata(raw["selection"]),
    )

    monkeypatch.setattr(
        main,
        "generate_sql",
        lambda question, schema, selections: (
            """
            SELECT year, indicator_id, value
            FROM observations
            ORDER BY year, indicator_id
            LIMIT 1000
            """
        ),
    )

    return retrieval


def test_single_indicator_still_works(monkeypatch):
    retrieval = configure_pipeline(
        monkeypatch, [POP]
    )

    outcome = asyncio.run(
        main.answer_question("Egypt's population")
    )

    assert len(outcome["selections"]) == 1
    assert retrieval.await_count == 1
    assert len(outcome["results"]) == 2
    assert outcome["s3_prefixes"] == []


def test_two_indicators_combined(monkeypatch):
    retrieval = configure_pipeline(
        monkeypatch, [POP, LIFE]
    )

    outcome = asyncio.run(
        main.answer_question(
            "Compare Egypt's population and life expectancy"
        )
    )

    assert retrieval.await_count == 2
    assert len(outcome["selections"]) == 2

    result = outcome["results"]

    assert len(result) == 4
    assert set(result["indicator_id"]) == {
        POP["indicator_id"],
        LIFE["indicator_id"],
    }

    actual = {
        (row.year, row.indicator_id): row.value
        for row in result.itertuples(index=False)
    }

    assert actual[(2022, POP["indicator_id"])] == 110_000_000
    assert actual[(2023, POP["indicator_id"])] == 112_000_000
    assert actual[(2022, LIFE["indicator_id"])] == 70
    assert actual[(2023, LIFE["indicator_id"])] == 71


def test_second_retrieval_failure_stops_pipeline(monkeypatch):
    retrieval = configure_pipeline(
        monkeypatch, [POP, LIFE]
    )

    calls = 0

    async def failing_retrieval(client, selection):
        nonlocal calls
        calls += 1

        if calls == 2:
            raise RuntimeError("Second indicator retrieval failed")

        return (
            {"selection": selection},
            {"selection": selection},
        )

    monkeypatch.setattr(
        main, "retrieve_dataset", failing_retrieval
    )

    sql_generator = AsyncMock()

    # Use a normal mock here because generate_sql is synchronous.
    from unittest.mock import Mock
    sql_generator = Mock()

    monkeypatch.setattr(
        main, "generate_sql", sql_generator
    )

    with pytest.raises(
        RuntimeError,
        match="Second indicator retrieval failed",
    ):
        asyncio.run(main.answer_question("Two indicators"))

    assert calls == 2
    sql_generator.assert_not_called()


def test_combined_data_preserves_indicator_identity(monkeypatch):
    configure_pipeline(monkeypatch, [POP, LIFE])

    outcome = asyncio.run(
        main.answer_question("Two indicators")
    )

    result = outcome["results"]

    assert result.groupby("indicator_id").size().to_dict() == {
        POP["indicator_id"]: 2,
        LIFE["indicator_id"]: 2,
    }
