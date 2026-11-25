"""
This is a prototype demonstrating how to use Qwen and the World Bank MCP
to answer analytical questions about World Bank indicators.
The prototype retrieves complete observations and metadata for multiple selected indicators,
normalizes the data, and creates an in-memory DuckDB database. 
It then asks Qwen to generate a SQL query based on the user's question and the live schema,
validates the SQL, executes it, returns the results, and answers the question.
It does not support CTEs, subqueries, window functions, or SELECT *, yet,
but it can handle multiple indicators and multiple countries in one question.
The prototype also persists the raw and normalized data to S3 for caching and future reference.
but no lazy ingestion/retreival of the data is performed. 
The prototype is not production-ready, pending lazy ingestion/loading implementation.
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
    generate_sql,
    choose_action
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
)

from agentic_framework.discovery import (
    discover_indicators,
)

from agentic_framework.controller import (
    run_analysis_loop,
)

from agentic_framework.model_runtime import model_session


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
    with model_session():
        return await _answer_question(question)

async def _answer_question(question: str) -> dict:
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
        metadata = indicators.to_dict("records")
        analysis = run_analysis_loop(
            question=question,
            con=con,
            schema=schema,
            metadata=metadata,
            selections=selections,
            initial_sql=sql,
            approved_tables=APPROVED_TABLES,
            choose_action=choose_action,
        )

        return {
            "question": question,
            "selections": selections,
            "schema": schema,
            "metadata": indicators.to_dict("records"),
            "s3_prefixes": s3_prefixes,
            **analysis,
        }

    finally:
        con.close()


if __name__ == "__main__":
    question = (
        "How did Switzerland's GDP per capita "
        "in current US dollars change between 2015 and 2023?"
    )

    outcome = asyncio.run(answer_question(question))

    print("\nAnswer:")
    print(outcome["answer"])

    if outcome["results"] is not None:
        print("\nQuery results:")
        print(outcome["results"].to_string(index=False))
