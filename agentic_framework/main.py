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

import boto3
from mcp import Client

from agentic_framework.llm_client import (
    get_model_completion,
    get_model_response,
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


APPROVED_TABLES = {"observations", "indicators"}

S3_BUCKET = os.getenv(
    "AGENT_S3_BUCKET",
    "webgis-population-app",
)
AWS_REGION = os.getenv("AWS_REGION", "eu-north-1")


def parse_model_json(content: str) -> dict:
    """Parse the structured indicator selection returned by Qwen."""

    if not content or not content.strip():
        raise ValueError("Qwen returned an empty selection.")

    content = content.strip()

    if content.startswith("```json"):
        content = content[7:]
        if content.endswith("```"):
            content = content[:-3]

    result = json.loads(content.strip())

    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object from Qwen.")

    required = {
        "database_id",
        "indicator_id",
        "country_code",
        "start_year",
        "end_year",
    }

    if not required.issubset(result):
        raise ValueError(
            f"Missing selection fields: {required - set(result)}"
        )

    database_id = result["database_id"]
    indicator_id = result["indicator_id"]
    country_code = result["country_code"]

    if not isinstance(database_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_]+", database_id
    ):
        raise ValueError("Invalid database identifier.")

    if not isinstance(indicator_id, str) or not re.fullmatch(
        r"[A-Za-z0-9_.]+", indicator_id
    ):
        raise ValueError("Invalid indicator identifier.")

    if not isinstance(country_code, str) or not re.fullmatch(
        r"[A-Z]{3}", country_code
    ):
        raise ValueError("Expected a three-letter country code.")

    for field in ("start_year", "end_year"):
        if type(result[field]) is not int:
            raise ValueError(f"{field} must be an integer.")

    if not (
        1960 <= result["start_year"]
        <= result["end_year"]
        <= 2100
    ):
        raise ValueError("Invalid year range.")

    return {key: result[key] for key in required}



async def discover_indicator(
    client: Client,
    question: str,
) -> dict:
    """Discover and validate one indicator using live MCP search results."""

    response = await client.list_tools()

    search_tool = next(
        (
            tool
            for tool in response.tools
            if tool.name == "data360_search_indicators"
        ),
        None,
    )

    if search_tool is None:
        raise RuntimeError("Indicator search tool unavailable.")

    tools = [{
        "type": "function",
        "function": {
            "name": search_tool.name,
            "description": search_tool.description or "",
            "parameters": search_tool.input_schema,
        },
    }]

    messages = [
        {
            "role": "system",
            "content": (
                "You are a World Bank indicator discovery assistant. "
                "Search using the provided MCP tool before selecting "
                "an indicator. Choose an indicator matching the user's "
                "concept, measurement, and unit. "
                "Handle one indicator, one country, and one annual "
                "year range. Return ONLY a JSON object with keys "
                "database_id, indicator_id, country_code, "
                "start_year, end_year. "
                "Use a three-letter country code and integer years. "
                "Never invent indicator identifiers. "
                "Do not include Markdown."
            ),
        },
        {"role": "user", "content": question},
    ]

    # Exact (database_id, indicator_id) pairs returned by MCP.
    discovered_ids = set()

    # Keep an optional diagnostic trace.
    trace_enabled = os.getenv("AGENT_TRACE_DISCOVERY") == "1"

    def trace(event, payload):
        if trace_enabled:
            print(f"\n[DISCOVERY] {event}")
            print(json.dumps(payload, indent=2, default=str))

    max_turns = 10

    for turn in range(max_turns):

        completion = get_model_completion(messages, tools)
        choice = completion.choices[0]
        message = choice.message
        calls = message.tool_calls or []

        # ----------------------------------------------
        # CASE A: Qwen returns a final selection
        # ----------------------------------------------

        if not calls:

            if not discovered_ids:
                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "No valid indicator has been discovered yet. "
                        "Search the MCP indicator catalog using the "
                        "provided tool before returning a selection."
                    ),
                })
                continue

            try:
                selection = parse_model_json(
                    message.content or ""
                )
            except (ValueError, TypeError) as exc:
                trace("invalid_final_response", {
                    "error": str(exc),
                })

                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "Your final response was not a valid "
                        "selection JSON. Return the required JSON "
                        "object using an indicator from the "
                        "previous MCP search results."
                    ),
                })
                continue

            selected_pair = (
                selection["database_id"],
                selection["indicator_id"],
            )

            if selected_pair not in discovered_ids:
                trace("invalid_indicator_id", {
                    "selected": selected_pair,
                    "valid_ids": sorted(discovered_ids),
                })

                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "The selected database_id and indicator_id "
                        "pair was not returned by MCP. "
                        "Select the exact identifiers from the "
                        "previous search results. "
                        "Do not reconstruct or abbreviate IDs. "
                        f"Available pairs: {sorted(discovered_ids)}"
                    ),
                })
                continue

            trace("selection_accepted", selection)
            return selection

        # ----------------------------------------------
        # CASE B: Qwen requests MCP search tools
        # ----------------------------------------------

        assistant_calls = []

        for call in calls:

            if call.function.name != "data360_search_indicators":
                raise ValueError(
                    "Unauthorized discovery tool."
                )

            arguments = call.function.arguments

            if isinstance(arguments, str):
                arguments = json.loads(arguments)

            if not isinstance(arguments, dict):
                raise ValueError(
                    "Invalid MCP tool arguments."
                )

            assistant_calls.append({
                "id": str(call.id),
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": json.dumps(arguments),
                },
            })

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": assistant_calls,
        })

        for proposed in assistant_calls:

            arguments = json.loads(
                proposed["function"]["arguments"]
            )

            trace("mcp_search_request", arguments)

            try:
                result = await call_data360_tool(
                    client,
                    "data360_search_indicators",
                    arguments,
                )

            except RuntimeError as exc:

                # Recover only from an unsuccessful search.
                # Unexpected MCP failures must still propagate.
                if "No indicators found" not in str(exc):
                    raise

                feedback = {
                    "status": "no_matches",
                    "error": str(exc),
                    "suggestion": (
                        "Try another formulation of the same "
                        "topic using simpler search terms."
                    ),
                }

            else:
                indicators = result.get("indicators", [])

                if not isinstance(indicators, list):
                    raise ValueError(
                        "Invalid MCP indicator-search response."
                    )

                for indicator in indicators:
                    database_id = indicator.get("database_id")
                    indicator_id = indicator.get("idno")

                    if database_id and indicator_id:
                        discovered_ids.add(
                            (database_id, indicator_id)
                        )

                # Send valid, compact JSON rather than
                # truncating the original response.
                feedback = {
                    "status": (
                        "ok" if indicators else "no_matches"
                    ),
                    "indicators": [
                        {
                            "database_id": item.get("database_id"),
                            "idno": item.get("idno"),
                            "name": item.get("name"),
                            "periodicity": item.get("periodicity"),
                            "time_period_range": item.get(
                                "time_period_range"
                            ),
                            "covers_country": item.get(
                                "covers_country"
                            ),
                            "definition": item.get(
                                "truncated_definition"
                            ),
                        }
                        for item in indicators
                    ],
                    "has_more": result.get("has_more", False),
                    "next_offset": result.get("next_offset"),
                }

            trace("mcp_search_result", feedback)

            messages.append({
                "role": "tool",
                "tool_call_id": proposed["id"],
                "content": json.dumps(
                    feedback,
                    default=str,
                ),
            })

    raise RuntimeError(
        "Indicator discovery failed after "
        f"{max_turns} model turns. "
        f"Discovered {len(discovered_ids)} candidate identifiers."
    )


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
    selection: dict,
) -> str:
    """Ask Qwen to generate DuckDB SQL using the live schema."""

    prompt = f"""
You are generating SQL for a DuckDB analytical database.

Return exactly one SELECT query.
Return ONLY SQL without Markdown or explanations.

Actual available database schema:

{schema}

The selected World Bank dataset is:
{json.dumps(selection, indent=2)}

Rules:
- Use only existing tables and columns.
- The observations table contains numerical observations.
- The indicators table contains indicator metadata.
- Use country_iso3 to filter countries.
- Filter observations by the selected indicator_id.
- Filter years to the requested range when appropriate.
- Never combine observations from different indicators.
- Use indicator_id to join observations and indicators.
- You may use an INNER JOIN on indicator_id.
- Do not use CTEs, subqueries, window functions or SELECT *.
- Use only read-only SELECT statements.
- Do not use external files, URLs or database functions.
- Use SQL compatible with DuckDB.
- Do not invent unavailable years or observations.
- Return at most 1000 result rows.

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
    """Run the complete World Bank analytical pipeline."""

    # Stage 1: Discover indicator and retrieve complete source data.
    async with Client(MCP_URL) as client:
        selection = await discover_indicator(client, question)

        print("Selected dataset:", selection)

        raw_observations, raw_metadata = await retrieve_dataset(
            client,
            selection,
        )

    prefix = build_s3_prefix(selection)
    skip_s3 = os.getenv("AGENT_SKIP_S3", "0") == "1"

    s3 = None if skip_s3 else boto3.client(
        "s3",
        region_name=AWS_REGION,
    )

    # Stage 2: Persist source responses before transformation.
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

    # Stage 3: Normalize the source responses.
    observations_df = normalize_observations(
        raw_observations,
        selection["indicator_id"],
    )

    indicators_df = normalize_metadata(raw_metadata)

    verify_observation_scope(observations_df, selection)

    # Stage 4: Persist normalized analytical tables.
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

    # Stage 5: Create the in-memory analytical database.
    con = create_connection({
        "observations": observations_df,
        "indicators": indicators_df,
    })

    try:
        # Stage 6: Discover the actual schema.
        schema = get_schema(con, APPROVED_TABLES)

        print("\nDuckDB schema:")
        print(schema)

        # Stage 7: Generate SQL from the question and schema.
        sql = generate_sql(question, schema, selection)

        print("\nGenerated SQL:")
        print(sql)

        # Stage 8: Validate and execute.
        # execute_query() calls sql_guard.validate_sql().
        result_df = execute_query(
            con,
            sql,
            APPROVED_TABLES,
        )

        return {
            "question": question,
            "selection": selection,
            "schema": schema,
            "sql": sql,
            "results": result_df,
            "metadata": indicators_df.to_dict("records"),
            "s3_prefix": None if skip_s3 else prefix,
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
