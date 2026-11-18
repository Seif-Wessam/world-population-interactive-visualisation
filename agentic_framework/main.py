"""
This is a prototype demonstrating how to use Qwen and the World Bank MCP
to answer analytical questions about World Bank indicators.
The prototype retrieves complete observations and metadata for a selected indicator,
normalizes the data, and creates an in-memory DuckDB database. 
It then asks Qwen to generate a SQL query based on the user's question and the live schema,
validates the SQL, executes it, and returns the results.
It is currently limited to one indicator, one country, and a specified year range. 
It does not support CTEs, subqueries, window functions, or SELECT *.
The prototype also persists the raw and normalized data to S3 for caching and future reference.
but no lazy ingestion/retreival of the data is performed. 
The prototype is intended for demonstration purposes only and is not production-ready.
"""
import asyncio
import json
import os
import re
from io import BytesIO
import pandas as pd

import boto3
from mcp import Client

from agentic_framework.llm_client import (
    get_model_completion,
    get_model_response,
    decompose_question
)

from agentic_framework.mcp_client import (
    MCP_URL,
    call_data360_tool,
    fetch_all_observations,
)
from agentic_framework.transform import (
    normalize_observations,
    normalize_metadata,
)
from agentic_framework.analytics import (
    create_connection,
    get_schema,
    execute_query,
)

from agentic_framework.discovery import (
    discover_indicators,
    discover_single_indicator,
    parse_model_json,
)


APPROVED_TABLES = {"observations", "indicators"}

S3_BUCKET = os.getenv(
    "AGENT_S3_BUCKET",
    "webgis-population-app",
)
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")


async def retrieve_dataset(
    client: Client,
    selection: dict,
) -> tuple[dict, dict]:
    """Retrieve complete observations and mandatory metadata."""

    observations = await fetch_all_observations(
        client,
        database_id=selection["database_id"],
        indicator_id=selection["indicator_id"],
        country_code=selection["country_code"],
        start_year=selection["start_year"],
        end_year=selection["end_year"],
    )

    metadata = await call_data360_tool(
        client,
        "data360_get_metadata",
        {
            "database_id": selection["database_id"],
            "indicator_id": selection["indicator_id"],
            "required_country": selection["country_code"],
        },
    )

    record = metadata.get("indicator_metadata", {})

    if (
        record.get("idno") != selection["indicator_id"]
        or record.get("database_id") != selection["database_id"]
    ):
        raise ValueError(
            "Retrieved metadata does not match the selected indicator."
        )

    if observations["count"] == 0:
        raise ValueError("No observations found for the requested scope.")

    return observations, metadata


def build_s3_prefix(selection: dict) -> str:
    """Create a predictable storage prefix for this dataset."""

    return (
        "agent_cache/prototype/"
        f"{selection['indicator_id']}/"
        f"{selection['country_code']}/"
        f"{selection['start_year']}-{selection['end_year']}"
    )


def save_json(s3, key: str, payload: dict) -> None:
    """Upload JSON to S3."""

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=json.dumps(
            payload,
            ensure_ascii=False,
            default=str,
        ).encode("utf-8"),
        ContentType="application/json",
    )


def save_parquet(s3, key: str, dataframe) -> None:
    """Serialize a pandas DataFrame as Parquet and upload it."""

    buffer = BytesIO()
    dataframe.to_parquet(buffer, index=False)

    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buffer.getvalue(),
        ContentType="application/octet-stream",
    )


def generate_sql(
    question: str,
    schema: str,
    selections: list[dict],
) -> str:
    """Ask Qwen to generate DuckDB SQL using the live schema."""

    prompt = f"""
    You are generating SQL for a DuckDB analytical database.

    Return exactly one SELECT statement.
    Return ONLY SQL without Markdown or explanations.

    Actual available database schema:

    {schema}

    Selected datasets:

    {json.dumps(selections, indent=2)}

    Rules:
    - Use only existing tables and columns.
    - The observations table contains rows from all selected indicators.
    - Every observation has indicator_id, country_iso3, year and value.
    - Preserve the distinction between indicators.
    - Filter by the exact relevant indicator IDs and countries.
    - Respect the requested time ranges.
    - The indicators table contains indicator metadata.
    - Do not introduce Cartesian products.
    - Do not use CTEs, subqueries, window functions or SELECT *.
    - Use only read-only SELECT statements.
    - Do not use external files, URLs or database functions.
    - Use DuckDB-compatible SQL.
    - Return at most 1000 rows.

    For questions involving multiple indicators:
    - You may use conditional aggregation to align their values by year.
    - Use CASE WHEN indicator_id = '...' THEN value END.
    - Use MAX with GROUP BY year to obtain one column per indicator,
    when appropriate and when observations are unique per indicator/year.
    - Do not join observations to itself.
    - Do not mix observations from different countries.
    - Use aliases that clearly identify the measurements.
    - If the user requests separate series, you may return a long-form
    result containing year, indicator_id and value instead.

    For single-indicator questions:
    - Continue using the original simple SELECT approach.

    User question:
    {question}
    """

    sql = get_model_response(prompt).strip()

    if not sql:
        raise ValueError("Qwen returned empty SQL.")

    return sql


def verify_observation_scope(
    observations_df,
    selection: dict,
) -> None:
    """Verify source data belongs to the requested dataset."""

    if not observations_df["indicator_id"].eq(
        selection["indicator_id"]
    ).all():
        raise ValueError("Unexpected indicator in observations.")

    if not observations_df["country_iso3"].eq(
        selection["country_code"]
    ).all():
        raise ValueError("Unexpected country in observations.")

    if not observations_df["year"].between(
        selection["start_year"],
        selection["end_year"],
    ).all():
        raise ValueError("Observations outside requested year range.")


async def answer_question(question: str) -> dict:
    """Run the analytical workflow for one or more indicators."""

    skip_s3 = os.getenv("AGENT_SKIP_S3", "0") == "1"

    s3 = None if skip_s3 else boto3.client(
        "s3",
        region_name=AWS_REGION,
    )

    all_observations = []
    all_indicators = []
    s3_prefixes = []

    # Stage 1: Decompose and discover.
    async with Client(MCP_URL) as client:
        selections = await discover_indicators(
            client,
            question,
        )

        print("Selected datasets:", selections)

        # Stage 2: Independently retrieve each dataset.
        for selection in selections:
            raw_observations, raw_metadata = await retrieve_dataset(
                client,
                selection,
            )

            prefix = build_s3_prefix(selection)

            # Preserve the existing persistence behaviour for now.
            if s3 is not None:
                save_json(
                    s3,
                    f"{prefix}/raw.json",
                    raw_observations,
                )
                save_json(
                    s3,
                    f"{prefix}/metadata.json",
                    raw_metadata,
                )

            # Stage 3: Normalize and validate independently.
            observations_df = normalize_observations(
                raw_observations,
                selection["indicator_id"],
            )

            indicators_df = normalize_metadata(raw_metadata)

            verify_observation_scope(
                observations_df,
                selection,
            )

            if s3 is not None:
                save_parquet(
                    s3,
                    f"{prefix}/observations.parquet",
                    observations_df,
                )
                save_parquet(
                    s3,
                    f"{prefix}/indicators.parquet",
                    indicators_df,
                )

            all_observations.append(observations_df)
            all_indicators.append(indicators_df)

            if s3 is not None:
                s3_prefixes.append(prefix)

    # Stage 4: Combine the normalized analytical data.
    observations = pd.concat(
        all_observations,
        ignore_index=True,
    )

    indicators = (
        pd.concat(all_indicators, ignore_index=True)
        .drop_duplicates(
            subset=["database_id", "indicator_id"]
        )
        .reset_index(drop=True)
    )

    # Identical indicator IDs from different databases must not
    # silently be treated as different datasets in DuckDB.
    if indicators["indicator_id"].duplicated().any():
        raise ValueError(
            "Indicator ID collision across databases. "
            "The analytical schema needs a composite identity."
        )

    # Prevent ambiguous duplicate observations after combination.
    if observations.duplicated(
        ["indicator_id", "country_iso3", "year"]
    ).any():
        raise ValueError(
            "Duplicate observations across selected datasets."
        )

    # Stage 5: Load both tables into a single DuckDB database.
    con = create_connection({
        "observations": observations,
        "indicators": indicators,
    })

    try:
        schema = get_schema(con, APPROVED_TABLES)

        print("\nDuckDB schema:")
        print(schema)

        # Stage 6: Generate one SQL query for the complete question.
        sql = generate_sql(
            question,
            schema,
            selections,
        )

        print("\nGenerated SQL:")
        print(sql)

        # Stage 7: Validate and execute.
        results = execute_query(
            con,
            sql,
            APPROVED_TABLES,
        )

        return {
            "question": question,
            "selections": selections,
            "schema": schema,
            "sql": sql,
            "results": results,
            "metadata": indicators.to_dict("records"),
            "s3_prefixes": s3_prefixes,
        }

    finally:
        con.close()


if __name__ == "__main__":
    question = (
        "How did Switzerland's GDP per capita "
        "in current US dollars change between 2015 and 2023?"
    )

    outcome = asyncio.run(answer_question(question))

    print("\nQuery results:")
    print(outcome["results"].to_string(index=False))
