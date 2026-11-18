"""
It asks Qwen to formulate a search, executes an MCP tool, provides results back to Qwen, allows retries,
validates the selected identifiers, and returns the selection.

That's agent orchestration, not an MCP client operation.
"""


from mcp import Client
import asyncio
import json
import re
from agentic_framework.llm_client import (
    decompose_question,
    get_model_completion,
)

from agentic_framework.mcp_client import call_data360_tool
import os


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



async def discover_single_indicator(
    client: Client,
    requirement: dict,
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
                "an indicator. Choose the indicator matching the "
                "specific required measurement, including its "
                "definition, unit and qualifiers. "
                "Return ONLY a JSON object with keys "
                "database_id, indicator_id, country_code, "
                "start_year, end_year. "
                "Preserve the required country and year range. "
                "Never invent indicator identifiers. "
                "Do not include Markdown."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Original question:\n{question}\n\n"
                "Discover an indicator for this specific requirement:\n"
                f"{json.dumps(requirement, indent=2)}"
            ),
        },
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
            
            
            # 1. Verify the indicator was actually returned by MCP.
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
                        "Choose an exact pair from the search results. "
                        f"Available pairs: {sorted(discovered_ids)}"
                    ),
                })
                continue

            # 2. Verify Qwen preserved the required scope.
            mismatched_fields = [
                field
                for field in (
                    "country_code",
                    "start_year",
                    "end_year",
                )
                if selection[field] != requirement[field]
            ]

            if mismatched_fields:
                trace("invalid_selection_scope", {
                    "fields": mismatched_fields,
                    "selection": selection,
                    "requirement": requirement,
                })

                messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                })
                messages.append({
                    "role": "user",
                    "content": (
                        "Your selection changed the required scope. "
                        f"Mismatched fields: {mismatched_fields}. "
                        "Preserve the country and requested years. "
                        "If the selected indicator does not cover "
                        "the requested period, search for another "
                        "suitable indicator."
                    ),
                })
                continue

            # 3. Both checks passed: accept the selection.
            selection["metric"] = requirement["metric"]

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


async def discover_indicators(
    client: Client,
    question: str,
) -> list[dict]:
    """Discover one validated indicator for each required measurement."""

    requirements = decompose_question(question)

    selections = []
    seen = set()

    for requirement in requirements:
        selection = await discover_single_indicator(
            client,
            requirement,
            question,
        )

        identity = (
            selection["database_id"],
            selection["indicator_id"],
            selection["country_code"],
            selection["start_year"],
            selection["end_year"],
        )

        # Avoid retrieving exactly the same dataset twice.
        if identity not in seen:
            selections.append(selection)
            seen.add(identity)

    if not selections:
        raise RuntimeError("No indicators were discovered.")

    return selections
