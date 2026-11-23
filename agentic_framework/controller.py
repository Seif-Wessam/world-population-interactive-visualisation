import pandas as pd
import json
import math
from numbers import Integral, Real
import duckdb
import re

from agentic_framework.analytics import (
    execute_query,
)
import logging

logger = logging.getLogger(__name__)

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


def run_analysis_loop(
    *,
    question,
    con,
    schema,
    metadata,
    selections,
    initial_sql,
    approved_tables,
    choose_action,
    max_turns=4,
    max_sql_attempts=5,
    max_state_bytes=48_000,
):
    """Run bounded analysis over an already-open DuckDB connection."""
    
    if max_turns < 0 or max_sql_attempts < 1 or max_state_bytes < 1 :
        raise ValueError("Invalid analysis limits.")
    registry = EvidenceRegistry()
    first_result_id = None
    sql_attempts = 0

    def execute_attempt(query):
        nonlocal sql_attempts, first_result_id
        # Count attempts, including rejected SQL.
        sql_attempts += 1
        feedback = run_sql_tool(
            query=query,
            con=con,
            approved_tables=approved_tables,
            registry=registry,
        )
        # Include the rejected SQL so Qwen can interpret its error.
        feedback = {**feedback, "query": query}
        # An evidence_error can still have a successfully executed,
        # registered DataFrame that remains available to the user.
        result_id = feedback.get("result_id")
        if first_result_id is None and result_id is not None:
            first_result_id = result_id
        return feedback

    def outcome(answer, status, reason):
        if first_result_id is None:
            sql, results = None, None
        else:
            sql, results = registry.get(first_result_id)
        return {
            "sql": sql,
            "results": results,
            "answer": answer,
            "analysis_status": status,
            "analysis_reason": reason,
        }

    def partial(reason):
        if first_result_id is None:
            return outcome(
                "No SQL query completed successfully, so no "
                "analytical result is available.",
                "failed",
                reason,
            )
        return outcome(
            "A query result is available, but the analysis "
            "could not be completed.",
            "partial",
            reason,
        )
    
    initial_feedback = execute_attempt(initial_sql)
    state = {
        "question": question,
        "schema": schema,
        "metadata": metadata,
        "selections": selections,
        "initial_evidence": initial_feedback.get("evidence"),
        "follow_ups": [],
    }
    if initial_feedback["status"] != "success":
        state["follow_ups"].append(initial_feedback)

    # max_turns ordinary calls, then one final answer-only call.
    for turn in range(max_turns + 1):
        allow_sql = (
            turn < max_turns
            and sql_attempts < max_sql_attempts
        )
        state["sql_attempts_remaining"] = (
            max_sql_attempts - sql_attempts
        )
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
            logger.warning(
                "Analysis turn %s: invalid action: %s",
                turn + 1,
                exc,
            )
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
                if first_result_id is None:
                    raise ValueError(
                        "No successful SQL result is available. "
                        "Request corrected SQL if SQL is allowed."
                    )
                answer = action.get("answer")
                if not isinstance(answer, str) or not answer.strip():
                    raise ValueError("Expected a non-empty answer.")
                answer = answer.strip()
            except ValueError as exc:
                logger.warning(
                    "Analysis turn %s: rejected answer: %s; proposal=%r",
                    turn + 1,
                    exc,
                    action.get("answer"),
                )
                state["follow_ups"].append({
                    "status": "answer_error",
                    "error": str(exc),
                })
                continue
            return outcome(
                answer,
                "complete",
                None,
            )
        if action.get("kind") == "sql":
            if not allow_sql:
                reason = (
                    "sql_attempt_limit_reached"
                    if sql_attempts >= max_sql_attempts
                    else "turn_limit_reached"
                )
                return partial(reason)

            feedback = execute_attempt(action.get("query"))
            state["follow_ups"].append(feedback)
            continue
        state["follow_ups"].append({
            "status": "invalid_action",
            "error": "Choose either 'sql' or 'answer'.",
        })

    return partial("no_valid_final_answer")