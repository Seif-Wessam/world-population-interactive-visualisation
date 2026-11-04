import pandas as pd
from dash import Dash
from plotly.colors import sequential

from dash_app.callbacks import register_callbacks
from dash_app.layout import create_layout, empty_history_figure
from dash_app.ui import create_population_globe


def make_app():
    data = pd.DataFrame(
        [
            dict(
                country="Egypt",
                country_iso3="EGY",
                date=2020,
                population=100,
                is_aggregate=False,
            ),
            dict(
                country="Egypt",
                country_iso3="EGY",
                date=2021,
                population=110,
                is_aggregate=False,
            ),
            dict(
                country="Egypt",
                country_iso3="EGY",
                date=2022,
                population=None,
                is_aggregate=False,
            ),
        ]
    )

    app = Dash(__name__)
    app.layout = create_layout(empty_history_figure(), 2021)
    register_callbacks(app, data)

    return app


def update(app, click=None, changed="population-globe.clickData"):
    outputs = [
        ("population-history", "figure"),
        ("history-message", "children"),
        ("country-name", "children"),
        ("country-population", "children"),
        ("country-year", "children"),
        ("population-globe", "clickData"),
    ]

    return app.server.test_client().post(
        "/_dash-update-component",
        json={
            "output": next(iter(app.callback_map)),
            "outputs": [
                dict(id=component_id, property=prop)
                for component_id, prop in outputs
            ],
            "inputs": [
                dict(
                    id="population-globe",
                    property="clickData",
                    value=click,
                ),
                dict(
                    id="reset-history",
                    property="n_clicks",
                    value=1,
                ),
            ],
            "state": [],
            "changedPropIds": [changed],
        },
    )


def test_select_clear_and_reselect_country():
    app = make_app()
    click = {"points": [{"location": "EGY"}]}

    result = update(app, click).json["response"]

    assert result["country-name"]["children"] == "Egypt"
    assert result["country-population"]["children"] == "110"
    assert "2021" in result["country-year"]["children"]

    # Country selection must not overwrite the globe.
    assert "population-globe" not in result

    line = result["population-history"]["figure"]["data"][0]["line"]
    assert line["color"] == "#440154"

    reset = update(
        app,
        click,
        "reset-history.n_clicks",
    ).json["response"]

    assert reset["population-globe"] == {"clickData": None}
    assert reset["country-name"]["children"] == "Choose a country"

    selected_again = update(app, click).json["response"]
    assert selected_again["country-name"]["children"] == "Egypt"


def test_empty_and_unknown_selections():
    app = make_app()

    empty = update(app)
    assert empty.status_code == 204 or empty.json["response"] == {}

    result = update(
        app,
        {"points": [{"location": "ZZZ"}]},
    ).json["response"]

    assert "No population history" in result["history-message"]["children"]


def test_layout_keeps_chart_mounted_and_viridis():
    app = make_app()

    layout = app.server.test_client().get("/_dash-layout")

    assert layout.status_code == 200
    assert b"population-history-container" in layout.data
    assert b'"display":"none"' not in layout.data

    records = pd.DataFrame(
        [
            dict(
                country="Egypt",
                country_iso3="EGY",
                date=2021,
                population=110,
            )
        ]
    )

    fig = create_population_globe(records, 2021)

    colours = [
        colour
        for _, colour in fig.layout.coloraxis.colorscale
    ]

    assert colours == sequential.Viridis
    assert fig.layout.uirevision == "population-globe"