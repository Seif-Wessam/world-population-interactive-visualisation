import boto3
from dash import Dash

from dash_app.callbacks import register_callbacks
from dash_app.data import load_population_data, prepare_population_data
from dash_app.layout import create_layout
from dash_app.ui import create_population_globe


BUCKET = "webgis-population-app"
OBJECT_KEY = "data/enriched_population_data.json"

# Boto3 uses the AWS credentials available in your environment.
s3_client = boto3.client("s3", region_name="eu-north-1")

raw_data = load_population_data(
    bucket_name=BUCKET,
    object_key=OBJECT_KEY,
    s3_client=s3_client,
)

population_data = prepare_population_data(raw_data)

# Keep individual economies with available population data.
economies = population_data.loc[
    (population_data["is_aggregate"] == False)
    & population_data["population"].notna()
].copy()

economies["country_iso3"] = (
    economies["country_iso3"]
    .fillna("")
    .str.strip()
    .str.upper()
)

economies = economies.loc[economies["country_iso3"] != ""]

# Select the latest year covering more than 200 economies.
economy_counts = economies.groupby("date")["country_id"].nunique()
eligible_years = economy_counts[economy_counts > 200]

if eligible_years.empty:
    raise ValueError(
        "No year has population data for more than 200 economies."
    )

latest_year = eligible_years.index.max()
map_data = economies.loc[economies["date"] == latest_year]

globe = create_population_globe(map_data, latest_year)

app = Dash(__name__, title="World Population Explorer")
server = app.server

app.layout = create_layout(globe, latest_year)

register_callbacks(app, population_data)


if __name__ == "__main__":
    app.run(debug=True)