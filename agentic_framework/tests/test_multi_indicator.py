import asyncio
import json

from agentic_framework import main
from agentic_framework.sql_guard import validate_sql


QUESTION = (
    "How did Egypt's population and life expectancy "
    "evolve between 2000 and 2023?"
)

REQUIREMENTS = [
    {
        "metric": "total population",
        "country_code": "EGY",
        "start_year": 2000,
        "end_year": 2023,
    },
    {
        "metric": "life expectancy at birth, total",
        "country_code": "EGY",
        "start_year": 2000,
        "end_year": 2023,
    },
]


def test_decomposition_two_measurements(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_model_response",
        lambda prompt: json.dumps(REQUIREMENTS),
    )

    actual = main.decompose_question(QUESTION)

    assert actual == REQUIREMENTS


def test_decomposition_removes_duplicates(monkeypatch):
    monkeypatch.setattr(
        main,
        "get_model_response",
        lambda prompt: json.dumps(
            [REQUIREMENTS[0], REQUIREMENTS[0]]
        ),
    )

    assert main.decompose_question(QUESTION) == [
        REQUIREMENTS[0]
    ]


def test_discovery_processes_both_requirements(monkeypatch):
    monkeypatch.setattr(
        main,
        "decompose_question",
        lambda question: REQUIREMENTS,
    )

    calls = []

    async def fake_discover(client, requirement, question):
        calls.append(requirement["metric"])

        indicator = (
            "WB_WDI_SP_POP_TOTL"
            if requirement["metric"] == "total population"
            else "WB_WDI_SP_DYN_LE00_IN"
        )

        return {
            **requirement,
            "database_id": "WB_WDI",
            "indicator_id": indicator,
        }

    monkeypatch.setattr(
        main,
        "discover_single_indicator",
        fake_discover,
    )

    selections = asyncio.run(
        main.discover_indicators(
            client=None,
            question=QUESTION,
        )
    )

    assert len(selections) == 2
    assert len(calls) == 2
    assert {
        item["indicator_id"] for item in selections
    } == {
        "WB_WDI_SP_POP_TOTL",
        "WB_WDI_SP_DYN_LE00_IN",
    }


def test_two_indicator_sql_is_allowed():
    sql = """
        SELECT
            year,
            MAX(
                CASE
                    WHEN indicator_id = 'POP'
                    THEN value
                END
            ) AS population,
            MAX(
                CASE
                    WHEN indicator_id = 'LIFE'
                    THEN value
                END
            ) AS life_expectancy
        FROM observations
        WHERE country_iso3 = 'EGY'
          AND indicator_id IN ('POP', 'LIFE')
        GROUP BY year
        ORDER BY year
        LIMIT 1000
    """

    allowed = {
        "observations": {
            "indicator_id",
            "country_iso3",
            "year",
            "value",
        },
        "indicators": {
            "indicator_id",
            "database_id",
            "name",
            "unit",
            "definition",
            "periodicity",
        },
    }

    validated = validate_sql(sql, allowed)

    assert validated
