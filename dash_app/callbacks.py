from dash import Input, Output, ctx, no_update

from dash_app.data import get_country_history
from dash_app.layout import EMPTY_MESSAGE, empty_history_figure
from dash_app.ui import create_population_history_chart


def register_callbacks(app, population_data):
    @app.callback(
        Output("population-history", "figure"),
        Output("history-message", "children"),
        Output("country-name", "children"),
        Output("country-population", "children"),
        Output("country-year", "children"),
        Output("population-globe", "clickData"),
        Input("population-globe", "clickData"),
        Input("reset-history", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_country_history(click_data, reset_clicks):
        if ctx.triggered_id == "reset-history":
            # Clear clickData so the same country can be selected again.
            # The globe figure is never updated, preserving its rotation.
            return (
                empty_history_figure(),
                EMPTY_MESSAGE,
                "Choose a country",
                "—",
                "Latest available population",
                None,
            )

        if not click_data or not click_data.get("points"):
            return (no_update,) * 6

        country_iso3 = click_data["points"][0].get("location")

        if not country_iso3:
            return (no_update,) * 6

        history = get_country_history(population_data, country_iso3)
        available = history.dropna(subset=["population"])

        if available.empty:
            return (
                empty_history_figure(),
                "No population history is available for this economy.",
                country_iso3,
                "—",
                "No available observation",
                no_update,
            )

        latest = available.sort_values("date").iloc[-1]

        return (
            create_population_history_chart(history),
            "",
            latest["country"],
            f'{latest["population"]:,.0f}',
            f'Latest available population · {int(latest["date"])}',
            no_update,
        )