from dash import dcc, html
import plotly.graph_objects as go


EMPTY_MESSAGE = (
    "Select a country on the globe to explore its population history."
)


def empty_history_figure():
    """Keep the chart mounted even before a country is selected."""
    fig = go.Figure()

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=45, r=20, t=20, b=45),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        annotations=[
            dict(
                text="Your country’s story appears here",
                x=0.5,
                y=0.5,
                xref="paper",
                yref="paper",
                showarrow=False,
                font=dict(size=13, color="#7a8090"),
            )
        ],
    )

    return fig


def create_layout(globe, year):
    return html.Main(
        [
            html.Header(
                [
                    html.Div(
                        [
                            html.P(
                                "WORLD BANK / POPULATION",
                                className="eyebrow",
                            ),
                            html.H1("World Population Explorer"),
                            html.P(
                                "Select a country to explore its population history.",
                                className="subtitle",
                            ),
                        ]
                    ),
                    html.Span(
                        f"Map year · {year}",
                        className="year-badge",
                    ),
                ],
                className="page-header",
            ),

            html.Div(
                [
                    # Left: interactive globe.
                    html.Section(
                        [
                            html.Div(
                                [
                                    html.H2("Explore the globe"),
                                    html.Span(
                                        "Drag to rotate · Click to select",
                                        className="hint",
                                    ),
                                ],
                                className="panel-heading",
                            ),
                            html.Div(
                                dcc.Graph(
                                    id="population-globe",
                                    figure=globe,
                                    responsive=True,
                                    style={"height": "100%", "width": "100%"},
                                    config={
                                        "displayModeBar": False,
                                        "scrollZoom": False,
                                    },
                                ),
                                className="map-viewport",
                            ),
                            html.P(
                                "Population uses a logarithmic Viridis scale. "
                                "Hover for exact values; grey areas have "
                                "no mapped value.",
                                className="map-note",
                            ),
                        ],
                        className="panel map-panel",
                    ),

                    # Right: reserved country details panel.
                    html.Section(
                        [
                            html.Div(
                                [
                                    html.P(
                                        "COUNTRY DETAILS",
                                        className="eyebrow",
                                    ),
                                    html.Button(
                                        "Clear selection",
                                        id="reset-history",
                                        n_clicks=0,
                                    ),
                                ],
                                className="panel-heading",
                            ),
                            html.H2(
                                "Choose a country",
                                id="country-name",
                            ),
                            html.Div(
                                [
                                    html.Div(
                                        "—",
                                        id="country-population",
                                        className="population-value",
                                    ),
                                    html.P(
                                        "Latest available population",
                                        id="country-year",
                                        className="metric-label",
                                    ),
                                ],
                                className="metric",
                            ),
                            html.P(
                                EMPTY_MESSAGE,
                                id="history-message",
                                role="status",
                                className="history-message",
                            ),
                            html.Div(
                                dcc.Graph(
                                    id="population-history",
                                    figure=empty_history_figure(),
                                    responsive=True,
                                    config={"displayModeBar": False},
                                ),
                                id="population-history-container",
                            ),
                        ],
                        className="panel details-panel",
                        **{"aria-label": "Selected country details"},
                    ),
                ],
                className="explorer-grid",
            ),

            html.Footer(
                "Source: World Bank · Economies include territories. "
                "Aggregate groups are excluded. Missing values are not zero."
            ),
        ],
        className="explorer-shell",
    )