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
    df = outcome["results"]
    if not isinstance(df, pd.DataFrame):
        raise TypeError("Agent results must be a pandas DataFrame.")

    selections = outcome.get("selections", [])
    clean = df.astype(object).where(pd.notna(df), None)
    table = dash_table.DataTable(
        data=clean.to_dict("records"),
        columns=[{"name": str(column), "id": str(column)} for column in df.columns],
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
        style_header={"fontWeight": "600", "backgroundColor": "#f5f6fa"},
    )
    summary = html.P(
        f"{len(selections)} indicator(s) · {len(df)} result row(s)",
        className="agent-summary",
    )
    metadata = html.Ul([
        html.Li(
            f"{s.get('metric', 'Indicator')}: "
            f"{s['database_id']} / {s['indicator_id']} "
            f"({s['country_code']}, {s['start_year']}–{s['end_year']})"
        )
        for s in selections
    ])
    return summary, table, outcome.get("sql", ""), metadata


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
            summary, table, sql, metadata = render_result(outcome)

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
