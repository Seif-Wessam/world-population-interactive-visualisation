import json
import pytest
import pandas as pd
from unittest.mock import Mock

from agentic_framework.controller import (
    EvidenceRegistry,
    evidence_json,
)
from agentic_framework import controller


def test_evidence_json_preserves_values_and_missing_data():
    # Arrange: register a small, known query result.
    registry = EvidenceRegistry()
    sql = "SELECT population FROM observations"
    results = pd.DataFrame({
        "population": [100.5, None],
    })
    result_id = registry.add(sql, results)

    # Act: prepare the evidence message and decode it.
    message = evidence_json(
        registry,
        result_id,
        max_rows=200,
        max_bytes=16_000,
    )
    payload = json.loads(message)

    # Assert: check the message's public contract.
    assert payload["result_id"] == result_id
    assert payload["sql"] == sql
    assert payload["columns"] == ["population"]
    assert payload["row_count"] == 2
    assert payload["rows_included"] is True
    assert payload["rows"] == [[100.5], [None]]


@pytest.mark.parametrize(
    "row_count, expected_included",
    [
        (200, True),
        (201, False),
    ],
)
def test_evidence_json_row_limit(row_count, expected_included):
    registry = EvidenceRegistry()
    results = pd.DataFrame({"value": [1] * row_count})
    result_id = registry.add(
        "SELECT value FROM observations",
        results,
    )

    payload = json.loads(
        evidence_json(
            registry,
            result_id,
            max_rows=200,
            max_bytes=16_000,
        )
    )

    assert payload["row_count"] == row_count
    assert payload["rows_included"] is expected_included

    if expected_included:
        assert payload["rows"] == [[1]] * row_count
    else:
        assert payload["rows"] is None
        assert payload["reason"] == "row_limit"

    # Withholding rows must not remove the underlying evidence.
    _, stored = registry.get(result_id)
    pd.testing.assert_frame_equal(stored, results)


def test_evidence_json_withholds_rows_when_values_exceed_byte_limit():
    registry = EvidenceRegistry()
    results = pd.DataFrame({"value": ["é" * 9_000]})
    result_id = registry.add(
        "SELECT value FROM observations",
        results,
    )

    message = evidence_json(
        registry,
        result_id,
        max_bytes=16_000,
    )
    payload = json.loads(message)

    assert payload["row_count"] == 1
    assert payload["rows_included"] is False
    assert payload["rows"] is None
    assert payload["reason"] == "serialized_size_limit"
    assert len(message.encode("utf-8")) <= 16_000

    _, stored = registry.get(result_id)
    pd.testing.assert_frame_equal(stored, results)


def test_evidence_json_rejects_oversized_metadata():
    registry = EvidenceRegistry()
    oversized_sql = "SELECT " + ("x" * 16_000)
    result_id = registry.add(
        oversized_sql,
        pd.DataFrame({"value": [1]}),
    )

    with pytest.raises(
        ValueError,
        match="Evidence metadata exceeds the message budget",
    ):
        evidence_json(
            registry,
            result_id,
            max_bytes=16_000,
        )


def test_run_sql_tool_registers_successful_result(monkeypatch):
    registry = controller.EvidenceRegistry()
    expected = pd.DataFrame({"population": [100.5]})
    connection = object()
    approved_tables = {"observations"}
    sql = "SELECT value AS population FROM observations"
    calls = []

    def fake_execute(con, query, tables):
        calls.append((con, query, tables))
        return expected

    monkeypatch.setattr(
        controller,
        "execute_query",
        fake_execute,
    )

    outcome = controller.run_sql_tool(
        query=sql,
        con=connection,
        approved_tables=approved_tables,
        registry=registry,
    )

    assert calls == [(connection, sql, approved_tables)]
    assert outcome["status"] == "success"
    assert outcome["result_id"] == "result_0"
    assert outcome["evidence"]["rows"] == [[100.5]]

    stored_sql, stored_results = registry.get("result_0")
    assert stored_sql == sql
    pd.testing.assert_frame_equal(stored_results, expected)


def test_run_sql_tool_preserves_initial_evidence_on_rejection(
    monkeypatch,
):
    registry = controller.EvidenceRegistry()
    initial = pd.DataFrame({"population": [100.5]})
    initial_sql = "SELECT value AS population FROM observations"
    registry.add(initial_sql, initial)

    def reject_query(con, query, tables):
        raise ValueError("Unsupported SQL.")

    monkeypatch.setattr(
        controller,
        "execute_query",
        reject_query,
    )

    outcome = controller.run_sql_tool(
        query="DELETE FROM observations",
        con=object(),
        approved_tables={"observations"},
        registry=registry,
    )

    assert outcome["status"] == "query_error"
    assert outcome["error"] == "Unsupported SQL."

    stored_sql, stored_results = registry.get("result_0")
    assert stored_sql == initial_sql
    pd.testing.assert_frame_equal(stored_results, initial)

    with pytest.raises(KeyError):
        registry.get("result_1")


def test_analysis_loop_can_answer_without_follow_up_sql(monkeypatch):
    calls = []

    def fake_choose_action(*, state_json, allow_sql):
        state = json.loads(state_json)
        calls.append(allow_sql)

        assert state["initial_evidence"]["result_id"] == "result_0"
        assert state["initial_evidence"]["rows"] == [[100.5]]

        return {
            "kind": "answer",
            "answer": {"test_proposal": True},
        }

    def fake_render_answer(proposal, registry):
        assert proposal == {"test_proposal": True}
        _, frame = registry.get("result_0")
        assert frame.iloc[0, 0] == 100.5
        return "Population was 100.5."

    def unexpected_sql(**kwargs):
        raise AssertionError("No follow-up SQL should execute.")

    monkeypatch.setattr(
        controller,
        "run_sql_tool",
        unexpected_sql,
    )

    outcome = controller.run_analysis_loop(
        question="What was the population?",
        con=object(),
        schema="test schema",
        metadata=[],
        selections=[],
        initial_sql="SELECT value FROM observations",
        initial_results=pd.DataFrame({"value": [100.5]}),
        approved_tables={"observations"},
        choose_action=fake_choose_action,
        render_answer=fake_render_answer,
    )

    assert outcome == {
        "answer": "Population was 100.5.",
        "analysis_status": "complete",
        "analysis_reason": None,
    }
    assert calls == [True]


@pytest.fixture
def analysis_inputs():
    return {
        "question": "How much did the population change?",
        "con": Mock(),
        "schema": "test schema",
        "metadata": [],
        "selections": [],
        "initial_sql": "SELECT year, value FROM observations",
        "initial_results": pd.DataFrame({
            "year": [2000, 2023],
            "value": [100.0, 120.0],
        }),
        "approved_tables": {"observations"},
        "render_answer": controller.render_answer,
    }


def answer_action(result_id, column):
    return {
        "kind": "answer",
        "answer": {
            "template": "The change was {{change}}.",
            "references": {
                "change": {
                    "result_id": result_id,
                    "row": 0,
                    "column": column,
                }
            },
        },
    }


def test_loop_uses_follow_up_evidence(monkeypatch, analysis_inputs):
    """A follow-up result reaches Qwen and supports the answer."""
    sql = "SELECT 20.0 AS change FROM observations LIMIT 1"
    execute = Mock(return_value=pd.DataFrame({"change": [20.0]}))
    monkeypatch.setattr(controller, "execute_query", execute)

    states = []

    def choose(*, state_json, allow_sql):
        state = json.loads(state_json)
        states.append(state)

        if len(states) == 1:
            return {"kind": "sql", "query": sql}

        feedback = state["follow_ups"][-1]
        assert feedback["status"] == "success"
        assert feedback["result_id"] == "result_1"
        assert feedback["evidence"]["rows"] == [[20.0]]

        return answer_action("result_1", "change")

    outcome = controller.run_analysis_loop(
        **analysis_inputs,
        choose_action=choose,
    )

    assert outcome["answer"] == "The change was 20.0."
    assert outcome["analysis_status"] == "complete"
    assert len(states) == 2

    execute.assert_called_once_with(
        analysis_inputs["con"],
        sql,
        analysis_inputs["approved_tables"],
    )
    analysis_inputs["con"].close.assert_not_called()


def test_loop_retries_invalid_answer_reference(
    monkeypatch, analysis_inputs
):
    """An invalid answer reference produces feedback and allows correction."""
    sql_tool = Mock(
        side_effect=AssertionError("SQL was not requested.")
    )
    monkeypatch.setattr(controller, "run_sql_tool", sql_tool)

    states = []

    def choose(*, state_json, allow_sql):
        state = json.loads(state_json)
        states.append(state)

        if len(states) == 1:
            return answer_action("result_7", "value")

        feedback = state["follow_ups"][-1]
        assert feedback["status"] == "answer_error"
        assert "Unknown result" in feedback["error"]

        return {
            "kind": "answer",
            "answer": {
                "template": "The initial value was {{initial}}.",
                "references": {
                    "initial": {
                        "result_id": "result_0",
                        "row": 0,
                        "column": "value",
                    }
                },
            },
        }

    outcome = controller.run_analysis_loop(
        **analysis_inputs,
        choose_action=choose,
    )

    assert outcome["answer"] == "The initial value was 100.0."
    assert outcome["analysis_status"] == "complete"
    assert len(states) == 2
    sql_tool.assert_not_called()


def test_loop_bounds_rejected_queries(monkeypatch, analysis_inputs):
    """Rejected SQL consumes the budget, and SQL cannot execute on the final turn."""
    execute = Mock(side_effect=ValueError("Unsupported SQL."))
    monkeypatch.setattr(controller, "execute_query", execute)

    allowed = []
    states = []
    original = analysis_inputs["initial_results"].copy(deep=True)

    def choose(*, state_json, allow_sql):
        allowed.append(allow_sql)
        states.append(json.loads(state_json))

        # Deliberately ignore the final-turn instruction.
        return {
            "kind": "sql",
            "query": "DELETE FROM observations",
        }

    outcome = controller.run_analysis_loop(
        **analysis_inputs,
        choose_action=choose,
        max_turns=2,
    )

    assert allowed == [True, True, False]
    assert execute.call_count == 2
    assert outcome["analysis_status"] == "partial"
    assert outcome["analysis_reason"] == "turn_limit_reached"

    assert [
        item["status"] for item in states[-1]["follow_ups"]
    ] == ["query_error", "query_error"]

    pd.testing.assert_frame_equal(
        analysis_inputs["initial_results"],
        original,
    )
    analysis_inputs["con"].close.assert_not_called()