
import pandas as pd

from agentic_workflow.agentic_framework.analytics import (
    load_population_data,
    create_connection,
    get_schema,
    execute_query,
    population_series
)
from llm_client import get_model_response


def generate_sql(question: str, schema: str) -> str:
    """Ask Qwen to translate a natural-language question into SQL."""

    prompt = f"""
You are an expert in DuckDB SQL.

Write one SELECT query.
Return ONLY SQL, without explanations or Markdown.

Table name: population

Available columns and types:
{schema}

Additional information:
- country_iso3 contains ISO3 country codes.
- date is a VARCHAR containing a four-digit year.
- population contains population values.
- is_aggregate identifies regional aggregates.
- Include the observation year and population in the output.

User question:
{question}
"""

    return get_model_response(prompt).strip()


def get_reference_series(df: pd.DataFrame) -> pd.Series:
    """Independently calculate the expected result using pandas."""

    filtered = df.loc[
        (df["country_iso3"] == "CHE")
        & (df["is_aggregate"] == False)
        & (df["date"].astype(int).between(2010, 2025))
    ].copy()

    return population_series(filtered)


def main():
    # 1. Load data and initialize DuckDB
    df = load_population_data()
    con = create_connection(df)

    try:
        # 2. Ask Qwen to generate SQL
        question = (
            "Show Switzerland's annual population "
            "from 2010 through 2025, ordered by year."
        )

        schema = get_schema(con)
        generated_sql = generate_sql(question, schema)

        print("Qwen-generated SQL:")
        print(generated_sql)

        if not generated_sql:
            raise ValueError("Qwen returned empty SQL.")

        # Temporary safeguard for this local experiment.
        # We'll implement automated SQL validation next.
        approval = input("Have you reviewed this SQL? Execute? [y/N]: ")

        if approval.strip().lower() != "y":
            print("Execution cancelled.")
            return

        # 3. Execute the reviewed query
        qwen_df = execute_query(con, generated_sql)

        # 4. Construct two comparable pandas Series
        actual = population_series(qwen_df)
        expected = get_reference_series(df)

        # 5. Verify complete year coverage
        if actual.index.tolist() != list(range(2010, 2026)):
            raise AssertionError("Missing or unexpected years.")

        # 6. Compare years and population values
        pd.testing.assert_series_equal(
            actual,
            expected,
            check_dtype=False
        )

        print("PASS: Qwen SQL matches pandas!")
        print(actual)

    finally:
        con.close()


if __name__ == "__main__":
    main()
