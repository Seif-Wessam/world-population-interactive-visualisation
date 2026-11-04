import numpy as np
import plotly.express as px


def create_population_globe(map_records, year):
    """Create a population globe from records for one year."""
    map_data = map_records.copy()

    map_data["country_iso3"] = (
        map_data["country_iso3"]
        .fillna("")
        .str.strip()
        .str.upper()
    )

    # A logarithm requires a positive population.
    positive_population = map_data["population"].where(
        map_data["population"] > 0
    )
    map_data["log_population"] = np.log10(positive_population)

    fig = px.choropleth(
        map_data,
        locations="country_iso3",
        locationmode="ISO-3",
        color="log_population",
        color_continuous_scale="Viridis",
        hover_name="country",
        hover_data={
            "country_iso3": True,
            "population": ":,.0f",
            "date": True,
            "log_population": False,
        },
        title=f"Population by economy — {year}",
        labels={"population": "Population",
                "country_iso3": "ISO3 code",
                "date": "Year"},
    )

    fig.update_coloraxes(
        colorbar_title="Population",
        colorbar_tickvals=[4, 5, 6, 7, 8, 9],
        colorbar_ticktext=["10K", "100K", "1M", "10M", "100M", "1B"],
    )

    fig.update_geos(
        projection_type="orthographic",
        showland=True,
        landcolor="lightgrey",
    )

    return fig


def create_population_history_chart(history):
    """Create a population-over-time chart for one economy.

    Expects records for one economy, with country, date and population
    columns. Returns a Plotly figure.
    """
    country_name = history["country"].iloc[0]

    fig = px.line(
        history,
        x="date",
        y="population",
        title=f"Population history — {country_name}",
        labels={
            "date": "Year",
            "population": "Population",
        },
        markers=True,
    )

    return fig