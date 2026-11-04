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
        labels={
            "population": "Population",
            "country_iso3": "ISO3 code",
            "date": "Year",
        },
    )

    fig.update_layout(
        title=None,
        uirevision="population-globe",
    )

    fig.update_coloraxes(
        colorbar_orientation="v",
        colorbar_x=-0.02,
        colorbar_xanchor="right",
        colorbar_y=0.5,
        colorbar_yanchor="middle",
        colorbar_len=0.75,
        colorbar_thickness=14,
        colorbar_title=dict(
            text="Population",
            side="top",
        ),
        colorbar_tickvals=[4, 5, 6, 7, 8, 9],
        colorbar_ticktext=["10K", "100K", "1M", "10M", "100M", "1B"],
    )

    fig.update_geos(
        projection_type="orthographic",
        showland=True,
        landcolor="#e8e8ee",
        bgcolor="white",
        showocean=True,
        oceancolor="#f7f8fb",
        showcountries=True,
        countrycolor="white",
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(
            family="Segoe UI, Arial, sans-serif",
            color="#555568",
        ),
        margin=dict(l=95, r=15, t=25, b=25),
        autosize=True,
    )

    return fig


def create_population_history_chart(history):
    """Create a population history chart for one economy."""
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
        markers=False,
        color_discrete_sequence=["#440154"],
    )

    fig.update_layout(
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        font=dict(
            family="Segoe UI, Arial, sans-serif",
            color="#555568",
        ),
        margin=dict(l=45, r=20, t=45, b=45),
        autosize=True,
    )

    return fig