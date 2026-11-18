
import pandas as pd
import pytest

from agentic_framework.analytics import (
    create_connection,
    execute_query,
)


TABLES = {"observations", "indicators"}

POP = "WB_WDI_SP_POP_TOTL"
LIFE = "WB_WDI_SP_DYN_LE00_IN"


@pytest.fixture
def con():
    observations = pd.DataFrame({
        "indicator_id": [POP, POP, LIFE, LIFE],
        "country_iso3": ["EGY"] * 4,
        "year": [2022, 2023, 2022, 2023],
        "value": [110_000_000, 112_000_000, 70, 71],
    })

    indicators = pd.DataFrame({
        "indicator_id": [POP, LIFE],
        "database_id": ["WB_WDI", "WB_WDI"],
        "name": ["Population", "Life expectancy"],
        "unit": ["People", "Years"],
        "definition": ["Population", "Life expectancy"],
        "periodicity": ["Annual", "Annual"],
    })

    connection = create_connection({
        "observations": observations,
        "indicators": indicators,
    })

    yield connection
    connection.close()


def test_conditional_aggregation_two_indicators(con):
    sql = f"""
        SELECT
            year,
            MAX(
                CASE WHEN indicator_id = '{POP}'
                     THEN value END
            ) AS population,
            MAX(
                CASE WHEN indicator_id = '{LIFE}'
                     THEN value END
            ) AS life_expectancy
        FROM observations
        WHERE country_iso3 = 'EGY'
          AND indicator_id IN ('{POP}', '{LIFE}')
        GROUP BY year
        ORDER BY year
        LIMIT 1000
    """

    result = execute_query(con, sql, TABLES)

    assert list(result.columns) == [
        "year", "population", "life_expectancy"
    ]
    assert result["year"].tolist() == [2022, 2023]
    assert result["population"].tolist() == [
        110_000_000, 112_000_000
    ]
    assert result["life_expectancy"].tolist() == [70, 71]


def test_observations_self_join_still_forbidden(con):
    sql = """
        SELECT a.year, a.value, b.value
        FROM observations a
        JOIN observations b
          ON a.year = b.year
        LIMIT 100
    """

    with pytest.raises(ValueError):
        execute_query(con, sql, TABLES)


def test_unauthorized_table_still_forbidden(con):
    with pytest.raises(ValueError):
        execute_query(
            con,
            "SELECT * FROM secrets LIMIT 10",
            TABLES,
        )


def test_write_operations_still_forbidden(con):
    with pytest.raises(ValueError):
        execute_query(
            con,
            "DELETE FROM observations",
            TABLES,
        )
