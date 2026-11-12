
import pandas as pd

from agentic_framework.analytics import (
    create_connection,
    get_schema,
    inspect_tables,
)


def test_two_table_connection():

    observations_df = pd.DataFrame({
        "indicator_id": ["TEST_GDP", "TEST_GDP"],
        "country_iso3": ["CHE", "CHE"],
        "year": [2022, 2023],
        "value": [90000.0, 95000.0],
    })

    indicators_df = pd.DataFrame({
        "indicator_id": ["TEST_GDP"],
        "database_id": ["TEST"],
        "name": ["GDP per capita"],
        "unit": ["USD"],
        "definition": ["Test indicator"],
        "periodicity": ["Annual"],
    })

    con = create_connection({
        "observations": observations_df,
        "indicators": indicators_df,
    })

    try:
        # 1. Verify the two DuckDB tables exist.
        tables = inspect_tables(
            con,
            {"observations", "indicators"},
        )

        assert set(tables) == {
            "observations",
            "indicators",
        }

        # 2. Verify dynamic schema discovery.
        schema = get_schema(
            con,
            {"observations", "indicators"},
        )

        assert '"observations"' in schema
        assert '"indicators"' in schema
        assert '"country_iso3"' in schema
        assert '"unit"' in schema

        # 3. Verify that observations reference metadata.
        result = con.execute("""
            SELECT o.year, o.value, i.unit
            FROM observations AS o
            JOIN indicators AS i
                ON o.indicator_id = i.indicator_id
            ORDER BY o.year
        """).fetchall()

        assert result == [
            (2022, 90000.0, "USD"),
            (2023, 95000.0, "USD"),
        ]

        # 4. Verify the DuckDB table is independent
        # of subsequent changes to its source DataFrame.
        observations_df.loc[0, "value"] = -1.0

        stored_value = con.execute("""
            SELECT value
            FROM observations
            WHERE year = 2022
        """).fetchone()[0]

        assert stored_value == 90000.0

    finally:
        con.close()
