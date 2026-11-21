import pandas as pd
import json
import math
from numbers import Integral, Real
import duckdb
from agentic_framework.analytics import (
    execute_query,
)
import re

class EvidenceRegistry:
    """SQL results for one question; accepts executed results only."""

    def __init__(self):
        self._entries = {}

    def add(self, sql: str, results: pd.DataFrame) -> str:
        if not sql.strip():
            raise ValueError("Evidence requires SQL.")

        if not results.columns.is_unique:
            raise ValueError("Evidence requires unique column names.")

        if not all(
            isinstance(column, str)
            for column in results.columns
        ):
            raise ValueError("Evidence requires string column names.")

        result_id = f"result_{len(self._entries)}"

        self._entries[result_id] = (
            sql,
            results.copy(deep=True),
        )

        return result_id

    def get(self, result_id: str) -> tuple[str, pd.DataFrame]:
        sql, results = self._entries[result_id]

        return sql, results.copy(deep=True)


def evidence_json(
    registry: EvidenceRegistry,
    result_id: str,
    *,
    max_rows: int = 200,
    max_bytes: int = 16_000,
) -> str:
    """Serialize a complete result, or explicitly withhold its rows."""
    if max_rows < 0 or max_bytes < 1:
        raise ValueError("Invalid evidence limits.")

    sql, frame = registry.get(result_id)

    payload = {
        "result_id": result_id,
        "sql": sql,
        "columns": list(frame.columns),
        "row_count": len(frame),
        "row_reference": "zero-based position, not DataFrame index",
        "rows_included": False,
        "rows": None,
    }

    def encode(value):
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

    def fits(text):
        return len(text.encode("utf-8")) <= max_bytes

    def scalar(value):
        if pd.isna(value):
            return None
        
        if isinstance(value, (str, bool)):
            return value
        
        if isinstance(value, Integral):
            return int(value)
        
        if isinstance(value, Real):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Non-finite evidence value.")
            return number

        raise ValueError(
            f"Unsupported evidence type: {type(value).__name__}"
        )

    if len(frame) <= max_rows:
        payload["rows"] = [
            [scalar(value) for value in row]
            for row in frame.itertuples(index=False, name=None)
        ]
        payload["rows_included"] = True

        message = encode(payload)
        if fits(message):
            return message

        reason = "serialized_size_limit"
    else:
        reason = "row_limit"

    payload.update(
        rows=None,
        rows_included=False,
        reason=reason,
        instruction=(
            "Rows withheld. Request a smaller SQL result against "
            "the original tables if values are needed. "
            "Do not infer unseen values."
        ),
    )

    message = encode(payload)
    if not fits(message):
        raise ValueError(
            "Evidence metadata exceeds the message budget."
        )

    return message


def run_sql_tool(
    *,
    query: str,
    con,
    approved_tables: set[str],
    registry: EvidenceRegistry,
) -> dict:
    """Execute guarded SQL and prepare feedback for the model."""

    if not isinstance(query, str) or not query.strip():
        return {
            "status": "query_error",
            "error": "Provide a non-empty SQL string.",
        }

    try:
        results = execute_query(
            con,
            query,
            approved_tables,
        )
    except (ValueError, duckdb.Error) as exc:
        return {
            "status": "query_error",
            "error": str(exc),
        }

    # Only successful executions become evidence.
    result_id = registry.add(query, results)

    try:
        message = evidence_json(registry, result_id)
    except ValueError as exc:
        return {
            "status": "evidence_error",
            "result_id": result_id,
            "error": str(exc),
        }

    return {
        "status": "success",
        "result_id": result_id,
        "evidence": json.loads(message),
    }


def render_answer(
    proposal: dict,
    registry: EvidenceRegistry,
    ) -> str:
    """Validate cell references and substitute numerical evidence."""

    if not isinstance(proposal, dict):
        raise ValueError("Answer proposal must be an object.")

    if set(proposal) != {"template", "references"}:
        raise ValueError("Answer requires template and references.")

    template = proposal["template"]
    references = proposal["references"]

    if not isinstance(template, str) or not template.strip():
        raise ValueError("Answer template must be non-empty text.")

    if not isinstance(references, dict):
        raise ValueError("References must be an object.")

    pattern = re.compile(r"\{\{([A-Za-z_]+)\}\}")
    names = set(pattern.findall(template))
    prose = pattern.sub("", template)

    if "{" in prose or "}" in prose:
        raise ValueError("Malformed answer placeholder.")

    if any(character.isnumeric() for character in prose):
        raise ValueError("Numerical values must use evidence references.")

    if names != set(references):
        raise ValueError(
            "Placeholders and reference names must match exactly."
        )

    replacements = {}

    for name in names:
        reference = references[name]

        if (
            not isinstance(reference, dict)
            or set(reference) != {"result_id", "row", "column"}
        ):
            raise ValueError(f"Invalid reference structure: {name}.")

        result_id = reference["result_id"]
        row = reference["row"]
        column = reference["column"]

        if not isinstance(result_id, str):
            raise ValueError("Result ID must be a string.")

        # bool is a subclass of int, so use an exact type check.
        if type(row) is not int or row < 0:
            raise ValueError("Row must be a non-negative integer.")

        if not isinstance(column, str):
            raise ValueError("Column must be a string.")

        try:
            _, frame = registry.get(result_id)
        except KeyError as exc:
            raise ValueError(f"Unknown result: {result_id}.") from exc

        if row >= len(frame):
            raise ValueError(f"Row outside result: {result_id}.")

        if column not in frame.columns:
            raise ValueError(f"Unknown column: {column}.")

        value = frame[column].iloc[row]

        if pd.isna(value):
            raise ValueError(f"Referenced value is missing: {name}.")

        if isinstance(value, bool):
            raise ValueError("Expected numerical evidence, not a boolean.")

        if isinstance(value, Integral):
            replacements[name] = str(int(value))
        elif isinstance(value, Real):
            number = float(value)
            if not math.isfinite(number):
                raise ValueError("Referenced value must be finite.")
            replacements[name] = str(number)
        else:
            raise ValueError("References must point to numerical values.")

    return pattern.sub(
        lambda match: replacements[match.group(1)],
        template,
    )


def run_analysis_loop(
    *,
    question,
    con,
    schema,
    metadata,
    selections,
    initial_sql,
    initial_results,
    approved_tables,
    choose_action,
    render_answer,
    max_turns=4,
    max_state_bytes=48_000,
):
    """Run bounded analysis over an already-open DuckDB connection."""

    if max_turns < 0 or max_state_bytes < 1:
        raise ValueError("Invalid analysis limits.")

    registry = EvidenceRegistry()
    initial_id = registry.add(initial_sql, initial_results)

    def partial(reason):
        return {
            "answer": (
                "The initial query result is available, but "
                "the additional analysis could not be completed."
            ),
            "analysis_status": "partial",
            "analysis_reason": reason,
        }

    try:
        initial_evidence = json.loads(
            evidence_json(registry, initial_id)
        )
    except ValueError:
        return partial("initial_evidence_error")

    state = {
        "question": question,
        "schema": schema,
        "metadata": metadata,
        "selections": selections,
        "initial_evidence": initial_evidence,
        "follow_ups": [],
    }

    # max_turns ordinary calls, then one final answer-only call.
    for turn in range(max_turns + 1):
        allow_sql = turn < max_turns

        state_json = json.dumps(
            state,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )

        if len(state_json.encode("utf-8")) > max_state_bytes:
            return partial("context_budget_reached")

        # The adapter must translate expected provider failures
        # into RuntimeError. Unexpected programming errors propagate.
        try:
            action = choose_action(
                state_json=state_json,
                allow_sql=allow_sql,
            )
        except RuntimeError:
            return partial("model_unavailable")
        except ValueError as exc:
            state["follow_ups"].append({
                "status": "invalid_action",
                "error": str(exc),
            })
            continue

        if not isinstance(action, dict):
            state["follow_ups"].append({
                "status": "invalid_action",
                "error": "Expected an action object.",
            })
            continue

        if action.get("kind") == "answer":
            try:
                answer = render_answer(
                    action.get("answer"),
                    registry,
                )
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Expected a non-empty answer.")
            except ValueError as exc:
                state["follow_ups"].append({
                    "status": "answer_error",
                    "error": str(exc),
                })
                continue

            return {
                "answer": answer,
                "analysis_status": "complete",
                "analysis_reason": None,
            }

        if action.get("kind") == "sql":
            # Enforce this in Python even if Qwen ignores instructions.
            if not allow_sql:
                return partial("turn_limit_reached")

            feedback = run_sql_tool(
                query=action.get("query"),
                con=con,
                approved_tables=approved_tables,
                registry=registry,
            )
            state["follow_ups"].append(feedback)
            continue

        state["follow_ups"].append({
            "status": "invalid_action",
            "error": "Choose either 'sql' or 'answer'.",
        })

    return partial("no_valid_final_answer")