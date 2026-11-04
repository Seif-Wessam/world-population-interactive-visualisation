"""HTTP and callback integration checks without AWS access."""
import pandas as pd
import pytest
from dash_app.app import create_app


@pytest.fixture
def app():
    rows = [dict(country=f"Economy {i}", country_id=str(i), country_iso3=f"X{i:02}",
                 date="2024", population=100+i, is_aggregate=False) for i in range(201)]
    rows.extend([
        dict(country="Egypt", country_id="EG", country_iso3="EGY", date="2020", population=100000000, is_aggregate=False),
        dict(country="Egypt", country_id="EG", country_iso3="EGY", date="2024", population=110000000, is_aggregate=False),
    ])
    return create_app(pd.DataFrame(rows))


def test_http_routes_and_assets(app):
    client = app.server.test_client()
    assert client.get("/healthz").json == {"status": "ok"}
    assert client.get("/").status_code == 200
    assert client.get("/assets/style.css").status_code == 200
    layout = client.get("/_dash-layout")
    assert layout.status_code == 200
    assert b"population-globe" in layout.data


def invoke_callback(app, click_data, changed="population-globe.clickData"):
    return app.server.test_client().post("/_dash-update-component", json={
        "output": next(iter(app.callback_map)),
        "outputs": [
            {"id": "population-history", "property": "figure"},
            {"id": "population-history-container", "property": "style"},
            {"id": "history-message", "property": "children"},
        ],
        "inputs": [
            {"id": "population-globe", "property": "clickData", "value": click_data},
            {"id": "reset-history", "property": "n_clicks", "value": 1},
        ], "changedPropIds": [changed], "state": [],
    })


def test_click_then_reset(app):
    response = invoke_callback(app, {"points": [{"location": "EGY"}]})
    assert response.status_code == 200
    result = response.json["response"]
    assert result["population-history-container"]["style"] == {"display": "block"}
    assert "Egypt" in result["population-history"]["figure"]["layout"]["title"]["text"]
    reset = invoke_callback(app, None, "reset-history.n_clicks").json["response"]
    assert reset["population-history-container"]["style"] == {"display": "none"}
    assert "Select an economy" in reset["history-message"]["children"]


def test_no_history_message(app):
    response = invoke_callback(app, {"points": [{"location": "ZZZ"}]})
    assert "No population history" in response.json["response"]["history-message"]["children"]
