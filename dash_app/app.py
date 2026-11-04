"""Dash application factory; importing this module does not contact AWS."""
import os

import boto3
from dash import Dash, dcc, html

from dash_app.callbacks import register_callbacks
from dash_app.data import load_population_data, prepare_population_data
from dash_app.ui import create_population_globe


def create_app(dataframe=None):
    if dataframe is None:
        dataframe = load_population_data(
            os.getenv("POPULATION_BUCKET", "webgis-population-app"),
            os.getenv("POPULATION_KEY", "data/enriched_population_data.json"),
            boto3.client("s3", region_name=os.getenv("AWS_REGION", "eu-north-1")),
        )
    population_data = prepare_population_data(dataframe)
    economies = population_data.loc[
        (population_data["is_aggregate"] == False)
        & population_data["population"].notna()
    ].copy()
    economies["country_iso3"] = economies["country_iso3"].fillna("").str.strip().str.upper()
    economies = economies.loc[economies["country_iso3"] != ""]
    counts = economies.groupby("date")["country_id"].nunique()
    eligible = counts[counts > 200]
    if eligible.empty:
        raise ValueError("No year has population data for more than 200 economies.")
    latest_year = int(eligible.index.max())
    map_data = economies.loc[economies["date"] == latest_year]
    app = Dash(__name__, title="World Population Explorer", update_title=None)
    app.layout = html.Main([
        html.Header([
            html.A("◉  WORLD / PEOPLE", href="/", className="wordmark"),
            html.A("World Bank data ↗", href="https://data.worldbank.org/indicator/SP.POP.TOTL",
                   target="_blank", rel="noopener noreferrer", className="source-link"),
        ], className="topbar"),
        html.Section([
            html.Div([
                html.P("A WORLD IN PERSPECTIVE", className="eyebrow"),
                html.H1(["Every place.", html.Br(), html.Span("A population story.")]),
                html.P("Explore the people behind the map. Select an economy to trace its population through time.", className="intro"),
            ]),
            html.Div([
                html.Div([html.Strong(str(latest_year)), html.Span("Map observation year")]),
                html.Div([html.Strong(str(map_data["country_id"].nunique())), html.Span("Economies represented")]),
                html.Div([html.Strong(str(int(population_data["date"].min())) + " →"), html.Span("Historical coverage")]),
            ], className="stats"),
        ], className="hero"),
        html.Section([
            html.Div([html.Div([html.P("01 / EXPLORE", className="eyebrow"), html.H2("Our world, in people")]),
                      html.Span("Drag to rotate · Click to explore", className="hint")], className="section-heading"),
            dcc.Graph(id="population-globe", figure=create_population_globe(map_data, latest_year),
                      config={"displayModeBar": False, "scrollZoom": False}, responsive=True),
            html.P("Colour uses a logarithmic scale so economies of very different sizes remain visible. Grey areas have no mapped value.", className="chart-note"),
        ], className="panel"),
        html.Section([
            html.Div([html.Div([html.P("02 / DISCOVER", className="eyebrow"), html.H2("A history of change")]),
                      html.Button("Clear selection", id="reset-history", n_clicks=0)], className="section-heading"),
            html.Div("Select an economy on the globe to reveal its population history.", id="history-message", role="status", className="empty-state"),
            html.Div(dcc.Graph(id="population-history", config={"displayModeBar": False}, responsive=True),
                     id="population-history-container", style={"display": "none"}),
        ], className="panel history-panel"),
        html.Footer([
            html.Span("Source: World Bank · Total population (SP.POP.TOTL)"),
            html.Span("Economies include territories. Aggregates are excluded; missing values are not zero."),
        ]),
    ], className="shell")
    register_callbacks(app, population_data)

    @app.server.get("/healthz")
    def health():
        return {"status": "ok"}

    return app


if __name__ == "__main__":
    create_app().run(debug=False, host="127.0.0.1", port=8050)
