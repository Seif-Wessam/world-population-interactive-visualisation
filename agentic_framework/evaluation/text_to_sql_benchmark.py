
import pandas as pd

from agentic_framework.analytics import (
    load_population_data,
    create_connection,
    get_schema,
    execute_query,
)
from agentic_framework.llm_client import get_model_response


# 1. Define the five benchmark questions
TEST_CASES = [
    {
        "id": "egypt",
        "question": "What was Egypt's total population in 2025?",
        "columns": ["population"],
    },
    {
        "id": "swiss_series",
        "question": (
            "Show Switzerland's annual population from 2010 "
            "through 2025 inclusive, ordered by year ascending."
        ),
        "columns": ["year", "population"],
    },
    {
        "id": "top_five",
        "question": (
            "Which five individual countries or economies "
            "had the highest population in 2025? "
            "Exclude aggregate regions and income groups. "
            "Sort by population descending."
        ),
        "columns": ["country_iso3", "population"],
    },
    {
        "id": "swiss_average",
        "question": (
            "What was Switzerland's average annual population "
            "from 2010 through 2025 inclusive?"
        ),
        "columns": ["avg_population"],
    },
    {
        "id": "france_change",
        "question": (
            "What was France's absolute population change "
            "between 2000 and 2025? "
            "Calculate population in 2025 minus population "
            "in 2000."
        ),
        "columns": ["population_increase"],
    },
]


# 2. Independently calculate reference answers in pandas
def build_references(df: pd.DataFrame) -> dict:
    data = df.loc[df["is_aggregate"] == False].copy()

    data["year"] = data["date"].astype(int)
    data["population"] = pd.to_numeric(data["population"])

    egypt = data.loc[
        (data["country_iso3"] == "EGY")
        & (data["year"] == 2025),
        ["population"]
    ].reset_index(drop=True)

    swiss = data.loc[
        (data["country_iso3"] == "CHE")
        & (data["year"].between(2010, 2025)),
        ["year", "population"]
    ].sort_values("year").reset_index(drop=True)

    top_five = (
        data.loc[
            (data["year"] == 2025)
            & data["population"].notna(),
            ["country_iso3", "population"]
        ]
        .sort_values(
            ["population", "country_iso3"],
            ascending=[False, True]
        )
        .head(5)
        .reset_index(drop=True)
    )

    swiss_average = pd.DataFrame({
        "avg_population": [swiss["population"].mean()]
    })

    france = data.loc[
        (data["country_iso3"] == "FRA")
        & data["year"].isin([2000, 2025])
    ].set_index("year")["population"]

    if len(egypt) != 1 or len(swiss) != 16:
        raise ValueError("Incomplete S3 reference observations.")

    if set(france.index) != {2000, 2025}:
        raise ValueError("Missing French reference observations.")

    france_change = pd.DataFrame({
        "population_increase": [
            france.loc[2025] - france.loc[2000]
        ]
    })

    return {
        "egypt": egypt,
        "swiss_series": swiss,
        "top_five": top_five,
        "swiss_average": swiss_average,
        "france_change": france_change,
    }


# 3. Construct the Text-to-SQL prompt
def generate_sql(question: str, schema: str, columns: list) -> str:
    
    prompt = f"""
    You are an expert in DuckDB SQL.

    Generate exactly one read-only SELECT query.
    Return ONLY SQL, without Markdown or explanations.

    Available database tables and their columns:
    {schema}

    Rules:
    - Use ONLY table names defined in the database schema above.
    - Use ONLY columns belonging to those tables.
    - Never invent tables or columns.
    - Use country_iso3 to identify countries.
    - For country filtering, use country_iso3 exclusively.
    - Never filter countries using the country or country_id columns.
    - Country names can differ from their commonly used names.
    - country_iso3 uses ISO 3166-1 alpha-3 country codes.
    - date contains four-digit years stored as VARCHAR.
    - Exclude aggregates when comparing individual countries.
    - Do not use joins, CTEs, subqueries, or window functions.
    - When comparing numerical observations from different years,
      prefer conditional aggregation using CASE WHEN.
    - Do not generate nested SELECT queries.

    Required output columns:
    {", ".join(columns)}

    User question:
    {question}
    """

    return get_model_response(prompt).strip()


# 4. Run the benchmark
def run_benchmark():
    df = load_population_data()
    references = build_references(df)
    con = create_connection(df)

    passed = 0

    try:
        schema = get_schema(con)

        for case in TEST_CASES:
            print(f"\n--- {case['id']} ---")

            stage = "SQL generation"

            try:
                sql = generate_sql(
                    case["question"],
                    schema,
                    case["columns"]
                )

                if not sql:
                    raise ValueError("Qwen returned empty SQL.")

                print("Generated SQL:")
                print(sql)

                # execute_query() calls validate_sql() first
                stage = "SQL validation or DuckDB execution"
                actual = execute_query(con, sql)

                # Check that Qwen returned the expected fields
                stage = "Result comparison"

                if set(actual.columns) != set(case["columns"]):
                    raise AssertionError(
                        f"Wrong output columns: "
                        f"{actual.columns.tolist()}"
                    )

                actual = actual[case["columns"]].copy()
                expected = references[case["id"]]

                # Normalize numeric types, not numerical values
                for column in actual.columns:
                    if column in {
                        "population",
                        "avg_population",
                        "population_increase",
                        "year",
                    }:
                        actual[column] = pd.to_numeric(
                            actual[column]
                        )

                pd.testing.assert_frame_equal(
                    actual.reset_index(drop=True),
                    expected.reset_index(drop=True),
                    check_dtype=False,
                    check_exact=False,
                    rtol=0,
                    atol=1e-6,
                )

                passed += 1
                print("PASS")
                print(actual.to_string(index=False))

            except Exception as error:
                print(f"FAIL during {stage}")
                print(f"{type(error).__name__}: {error}")

        print(
            f"\nBENCHMARK RESULT: {passed}/{len(TEST_CASES)} passed"
        )

    finally:
        con.close()


if __name__ == "__main__":
    run_benchmark()
