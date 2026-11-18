"""Presentation-only Dash components for the agentic analytics page."""

from dash import dcc, html


EXAMPLE_QUESTION = (
    "For Egypt, return annual total population and life expectancy at birth, "
    "total (years), from 2000 through 2023. Return year, population and "
    "life_expectancy, ordered by year ascending."
)


def create_agent_layout():
    """Build the agent page without making inference or network requests."""
    return html.Section(
        [
            html.Div(
                [
                    html.P("WORLD BANK / AI ANALYTICS", className="eyebrow"),
                    html.H2("Ask the World Bank data analyst"),
                    html.P(
                        "Describe the indicators, country and years you want to explore. "
                        "The agent discovers data through World Bank Data360 and "
                        "runs validated read-only SQL in DuckDB.",
                        className="subtitle",
                    ),
                ],
                className="agent-heading",
            ),
            html.Label("Your question", htmlFor="agent-question"),
            dcc.Textarea(
                id="agent-question",
                value=EXAMPLE_QUESTION,
                placeholder="Ask a question about World Bank indicators...",
                maxLength=1500,
                className="agent-question",
            ),
            html.Div(
                [
                    html.Button("Run analysis", id="agent-submit", n_clicks=0),
                    html.Span(
                        "Local MVP · Live requests are opt-in",
                        className="hint",
                    ),
                ],
                className="agent-actions",
            ),
            dcc.Loading(
                id="agent-loading",
                type="circle",
                children=html.Div(
                    [
                        html.P(
                            "Submit a question to see the analysis.",
                            id="agent-status",
                            role="status",
                            className="history-message",
                        ),
                        html.Div(id="agent-summary"),
                        html.Div(id="agent-results"),
                        html.Details(
                            [
                                html.Summary("Generated SQL"),
                                html.Pre(id="agent-sql", className="agent-sql"),
                            ],
                            className="agent-details",
                        ),
                        html.Details(
                            [
                                html.Summary("Selected indicators and metadata"),
                                html.Div(id="agent-metadata"),
                            ],
                            className="agent-details",
                        ),
                    ]
                ),
            ),
        ],
        className="panel agent-panel",
    )
