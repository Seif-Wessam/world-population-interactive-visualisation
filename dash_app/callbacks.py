from dash import Input, Output, callback, ctx, no_update

from dash_app.data import get_country_history

from dash_app.ui import create_population_history_chart


def register_callbacks(app, population_data):
    """Connect globe clicks and the reset button to the history chart."""

    @app.callback(
        Output("population-history", "figure"),
        Output("population-history-container", "style"),
        Output("history-message", "children"),
        Input("population-globe", "clickData"),
        Input("reset-history", "n_clicks"),
        prevent_initial_call=True,
    )
    def update_country_history(click_data, reset_clicks):
        if ctx.triggered_id == "reset-history":
            return {}, {"display": "none"}, ""

        if not click_data or not click_data.get("points"):
            return no_update, no_update, no_update

        country_iso3 = click_data["points"][0].get("location")

        if not country_iso3:
            return no_update, no_update, no_update

        history = get_country_history(population_data, country_iso3)

        if history.empty or history["population"].notna().sum() == 0:
            return {}, {"display": "none"}, (
                "No population history is available for this economy."
            )

        country_name = history["country"].iloc[0]

        fig = create_population_history_chart(history)

        return fig, {"display": "block"}, ""