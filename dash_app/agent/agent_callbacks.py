"""Dash event handling for the agent. No LLM calls at module import time."""

import asyncio
import os

import pandas as pd
from dash import Input, Output, State, dash_table, html
from dash.exceptions import PreventUpdate


def run_agent(question: str) -> dict:
    """Thin adapter to the existing asynchronous analytics pipeline.

    Development-only synchronous adapter. Do not expose this directly from a
    public Lambda callback; use a bounded background job worker first.
    """
    from agentic_framework.main import answer_question

    return asyncio.run(answer_question(question))


def render_result(outcome: dict):
    """Convert analytical results into Dash presentation components."""
    df = outcome.get("results")

    if df is not None and not isinstance(df, pd.DataFrame):
        raise TypeError("Agent results must be a pandas DataFrame or None.")

    selections = outcome.get("selections", [])

    if df is None:
        table = html.P("No query result is available.")
        row_count = 0
    else:
        row_count = len(df)
        clean = df.astype(object).where(pd.notna(df), None)

        # Keep your existing dash_table.DataTable(...) construction here.
        table = dash_table.DataTable(
            id="agent-result-table",
            data=clean.to_dict("records"),
            columns=[
                {"name": str(column), "id": str(column)}
                for column in df.columns
            ],
            page_size=15,
            sort_action="native",
            filter_action="native",
            style_table={"overflowX": "auto"},
            style_cell={
                "fontFamily": "Segoe UI, Arial, sans-serif",
                "fontSize": "13px",
                "textAlign": "left",
                "padding": "10px",
                "minWidth": "100px",
            },
            style_header={
                "fontWeight": "600",
                "backgroundColor": "#f5f6fa",
            },
        )

    summary = html.P(
        f"{len(selections)} indicator(s) · {row_count} result row(s)",
        className="agent-summary",
    )
    metadata = html.Ul([
        html.Li(
            f"{s.get('metric', 'Indicator')}: "
            f"{s['database_id']} / {s['indicator_id']} "
            f"({s['country_code']}, {s['start_year']}-{s['end_year']})"
        )
        for s in selections
    ])
    return summary, table, outcome.get("sql") or "", metadata


def render_analysis(outcome: dict):
    """Display workflow status, answer, and preserved query results."""
    labels = {
        "complete": (
            "Answer generated.",
            "#166534",
        ),
        "partial": (
            "Analysis incomplete — available results are shown below.",
            "#92400e",
        ),
        "failed": (
            "Analysis could not produce a query result.",
            "#991b1b",
        ),
    }

    status = outcome.get("analysis_status")
    if status not in labels:
        raise ValueError("Unexpected analysis status.")

    answer = outcome.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Expected a non-empty answer.")

    summary, table, sql, metadata = render_result(outcome)
    label, color = labels[status]

    content = [
        html.P(
            label,
            id="agent-analysis-status",
            role="status",
            style={"color": color, "fontWeight": "600"},
        ),
        html.H3("Answer"),
        html.Div(
            answer.strip(),
            id="agent-answer",
            style={
                "whiteSpace": "pre-wrap",
                "lineHeight": "1.6",
                "marginBottom": "12px",
            },
        ),
        html.P(
            "AI-generated explanation. Review the available data "
            "and SQL for supporting evidence.",
            className="hint",
        ),
    ]

    if outcome.get("results") is not None:
        content.extend([
            html.H3("Available query result"),
            html.P(
                "This table preserves the first successful query. "
                "Additional calculations may have been used in the answer.",
                className="hint",
            ),
        ])

    content.extend([summary, table])

    return html.Div(content), sql, metadata

def register_agent_callbacks(app):
    @app.callback(
        Output("agent-results", "children"),
        Output("agent-sql", "children"),
        Output("agent-metadata", "children"),
        Input("agent-submit", "n_clicks"),
        State("agent-question", "value"),
        prevent_initial_call=True,
    )
    def submit_question(n_clicks, question):
        if not n_clicks:
            raise PreventUpdate

        # Every callback branch must return exactly three values.
        def message_result(message):
            return html.P(message), "", None

        question = (question or "").strip()

        if not question:
            return message_result("Please enter a question.")

        if len(question) > 1500:
            return message_result(
                "Question exceeds 1,500 characters."
            )

        if os.getenv("AGENT_UI_LIVE") != "1":
            return message_result(
                "Live analysis is disabled. "
                "Set AGENT_UI_LIVE=1 to enable local inference."
            )

        # Require explicit no-write configuration.
        if os.getenv("AGENT_SKIP_S3") != "1":
            return message_result(
                "Set AGENT_SKIP_S3=1 before starting the app."
            )

        try:
            outcome = run_agent(question)
            return render_analysis(outcome)

        except Exception:
            app.logger.exception("Agent analysis failed")
            return message_result(
                "Analysis failed. Check the server logs for details."
            )

        return (
            html.Div([
                html.P(
                    "Analysis complete.",
                    className="agent-status-success",
                ),
                summary,
                table,
            ]),
            sql,
            metadata,
        )
