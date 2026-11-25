"""Offline tests for the Dash agent page and its synchronous MVP callback.

Run from the repository root:
    python -m pytest dash_app/agent/tests/test_agent_gui.py -v

Assumes dash_app/agent/layout.py and dash_app/agent/callbacks.py are in place.
"""

import logging
from dash import html

import pandas as pd
import pytest
from dash import dash_table
from dash.exceptions import PreventUpdate

from dash_app.agent import agent_callbacks 
from dash_app.agent.agent_layout import create_agent_layout


class FakeApp:
    """Capture callbacks without creating a Dash server or loading S3."""

    logger = logging.getLogger("test_agent_gui")

    def __init__(self):
        self.outputs = None
        self.callback_fn = None

    def callback(self, *args, **kwargs):
        # The initial Output declarations precede Input/State declarations.
        self.outputs = [item for item in args if type(item).__name__ == "Output"]

        def register(fn):
            self.callback_fn = fn
            return fn

        return register


@pytest.fixture
def callback():
    app = FakeApp()
    agent_callbacks.register_agent_callbacks(app)
    assert app.callback_fn is not None
    return app


@pytest.fixture
def outcome():
    return {
        "results": pd.DataFrame(
            {"year": [2022, 2023], "population": [112618250.0, 114535772.0],
             "life_expectancy": [71.010, 71.633]}
        ),
        "sql": "SELECT year, population, life_expectancy FROM observations",
        "selections": [
            {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL",
             "metric": "Population, total", "country_code": "EGY",
             "start_year": 2000, "end_year": 2023},
            {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
             "metric": "Life expectancy", "country_code": "EGY",
             "start_year": 2000, "end_year": 2023},
        ],
        "answer": "Egypt's population increased over the observed period.",
        "analysis_status": "complete",
        "analysis_reason": None,
    }


def walk(component):
    """Traverse Dash components without rendering a browser page."""
    if isinstance(component, (tuple, list)):
        for child in component:
            yield from walk(child)
    elif hasattr(component, "to_plotly_json"):
        yield component
        yield from walk(getattr(component, "children", None))


def test_layout_has_all_expected_ids(callback):
    component_ids = {getattr(x, "id", None) for x in walk(create_agent_layout())}
    required = {
        "agent-question", "agent-submit", "agent-summary",
        "agent-results", "agent-sql", "agent-metadata",
    }
    assert required <= component_ids
    callback_ids = {out.component_id for out in callback.outputs}
    assert callback_ids <= component_ids


def test_render_result_contains_correct_table_and_metadata(outcome):
    summary, table, sql, metadata = agent_callbacks.render_result(outcome)
    assert "2 indicator(s)" in summary.children
    assert "2 result row(s)" in summary.children
    assert isinstance(table, dash_table.DataTable)
    assert [c["id"] for c in table.columns] == [
        "year", "population", "life_expectancy"
    ]
    assert table.data[1]["population"] == 114535772.0
    assert sql == outcome["sql"]
    assert len(metadata.children) == 2


def test_render_result_handles_missing_values(outcome):
    outcome["results"].loc[0, "life_expectancy"] = float("nan")
    _, table, _, _ = agent_callbacks.render_result(outcome)
    assert table.data[0]["life_expectancy"] is None


def test_render_result_rejects_non_dataframe(outcome):
    outcome["results"] = [{"year": 2023}]
    with pytest.raises(TypeError, match="DataFrame"):
        agent_callbacks.render_result(outcome)


def test_no_click_does_not_trigger_agent(callback):
    with pytest.raises(PreventUpdate):
        callback.callback_fn(0, "Population in Egypt")


@pytest.mark.parametrize("question,expected", [
    ("   ", "Please enter a question"),
    ("x" * 1501, "1,500 characters"),
])
def test_invalid_input_returns_correct_number_of_outputs(
    callback, monkeypatch, question, expected
):
    monkeypatch.setenv("AGENT_UI_LIVE", "1")
    monkeypatch.setenv("AGENT_SKIP_S3", "1")
    values = callback.callback_fn(1, question)
    assert len(values) == len(callback.outputs)
    assert expected in values[0].children


def test_live_mode_is_opt_in(callback, monkeypatch):
    monkeypatch.delenv("AGENT_UI_LIVE", raising=False)
    values = callback.callback_fn(1, "How has population changed?")
    assert len(values) == len(callback.outputs)
    assert "disabled" in values[0].children.lower()


def test_requires_s3_write_protection(callback, monkeypatch):
    monkeypatch.setenv("AGENT_UI_LIVE", "1")
    monkeypatch.delenv("AGENT_SKIP_S3", raising=False)
    values = callback.callback_fn(1, "How has population changed?")
    assert len(values) == len(callback.outputs)
    assert "AGENT_SKIP_S3=1" in values[0].children

@pytest.mark.parametrize(
    "status,label",
    [
        ("complete", "Answer generated."),
        (
            "partial",
            "Analysis incomplete — available results are shown below.",
        ),
    ],
)
def test_answer_and_available_results_are_displayed(
    callback, monkeypatch, outcome, status, label
):
    monkeypatch.setenv("AGENT_UI_LIVE", "1")
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    outcome["analysis_status"] = status
    if status == "partial":
        outcome["analysis_reason"] = "turn_limit_reached"
        outcome["answer"] = (
            "A query result is available, but the analysis "
            "could not be completed."
        )

    seen = []

    def fake_agent(question):
        seen.append(question)
        return outcome

    monkeypatch.setattr(agent_callbacks, "run_agent", fake_agent)

    values = callback.callback_fn(1, "  How has Egypt changed?  ")

    assert seen == ["How has Egypt changed?"]
    assert len(values) == len(callback.outputs)

    components = list(walk(values[0]))
    by_id = {
        getattr(component, "id", None): component
        for component in components
        if getattr(component, "id", None)
    }

    assert by_id["agent-analysis-status"].children == label
    assert by_id["agent-answer"].children == outcome["answer"]

    table = by_id["agent-result-table"]
    assert isinstance(table, dash_table.DataTable)
    assert len(table.data) == len(outcome["results"])
    assert table.data[1]["population"] == 114535772.0
    assert values[1] == outcome["sql"]

    assert components.index(by_id["agent-answer"]) < components.index(table)


def test_agent_error_is_safely_reported(callback, monkeypatch):
    monkeypatch.setenv("AGENT_UI_LIVE", "1")
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    def broken(_question):
        raise RuntimeError("secret backend error")

    monkeypatch.setattr(agent_callbacks, "run_agent", broken)
    values = callback.callback_fn(1, "Population?")
    assert len(values) == len(callback.outputs)
    assert "Analysis failed" in values[0].children
    assert "secret backend error" not in str(values)


def test_failed_outcome_without_dataframe(
    callback, monkeypatch, outcome
):
    monkeypatch.setenv("AGENT_UI_LIVE", "1")
    monkeypatch.setenv("AGENT_SKIP_S3", "1")

    outcome.update(
        results=None,
        sql=None,
        answer="No SQL query completed successfully.",
        analysis_status="failed",
        analysis_reason="sql_attempt_limit_reached",
    )
    monkeypatch.setattr(
        agent_callbacks, "run_agent", lambda question: outcome
    )

    values = callback.callback_fn(1, "Population in Egypt?")
    components = list(walk(values[0]))

    assert len(values) == len(callback.outputs)
    assert values[1] == ""
    assert not any(
        isinstance(component, dash_table.DataTable)
        for component in components
    )

    answer = next(
        component
        for component in components
        if getattr(component, "id", None) == "agent-answer"
    )
    assert answer.children == outcome["answer"]




from collections import Counter


def test_agent_layout_ids_are_unique():
    ids = [
        component.id
        for component in walk(create_agent_layout())
        if getattr(component, "id", None) is not None
    ]
    duplicates = {
        component_id: count
        for component_id, count in Counter(ids).items()
        if count > 1
    }

    assert not duplicates, f"Duplicate component IDs: {duplicates}"