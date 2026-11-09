
import asyncio
import json

import boto3
import pandas as pd

from agentic_framework.main import answer_question


BUCKET = "webgis-population-app"
KEY = "data/enriched_population_data.json"


# 1. Our three test cases
TEST_CASES = [
    {
        "name": "Latest population",
        "country": "EGY",
        "years": None,
        "question": (
            "What is Egypt's latest available annual total "
            "population value in World Bank WDI? "
            "Retrieve the observation and its year."
        )
    },
    {
        "name": "Historical population",
        "country": "FRA",
        "years": [2020],
        "question": (
            "What was France's total population in 2020 "
            "according to World Bank WDI?"
        )
    },
    {
        "name": "Historical time series",
        "country": "CHE",
        "years": list(range(2010, 2026)),
        "question": (
            "Retrieve Switzerland's annual total population "
            "for every year from 2010 through 2025 inclusive, "
            "using World Bank WDI. Retrieve all observations."
        )
    }
]


# 2. Load our existing reference dataset from S3
def load_s3_data():
    s3 = boto3.client("s3", region_name="eu-north-1")

    response = s3.get_object(Bucket=BUCKET, Key=KEY)
    records = json.loads(response["Body"].read())

    return pd.DataFrame(records)


# 3. Extract a country's population series from S3
def get_s3_series(dataframe, country):
    df = dataframe.loc[
        (dataframe["country_iso3"] == country)
        & (dataframe["is_aggregate"] == False)
    ].copy()

    df["year"] = df["date"].astype(int)
    df["population"] = pd.to_numeric(
        df["population"]
    ).astype("Int64")

    return df.set_index("year")["population"].sort_index()


# 4. Extract observations from the MCP responses
def get_mcp_series(data_responses, country):
    records = []

    for payload in data_responses:
        if not isinstance(payload, dict):
            raise ValueError("Unexpected MCP response format.")

        if payload.get("error"):
            raise ValueError(payload["error"])

        # Incomplete pages must never silently pass.
        if payload.get("has_more"):
            raise ValueError("MCP response has uncollected pages.")

        metadata = payload.get("metadata", {})

        if metadata.get("idno") != "WB_WDI_SP_POP_TOTL":
            raise ValueError("Wrong population indicator selected.")

        records.extend(payload.get("data", []))

    if not records:
        raise ValueError("No MCP observations were retrieved.")

    df = pd.DataFrame(records)

    if set(df["REF_AREA"]) != {country}:
        raise ValueError("MCP returned an unexpected country.")

    if not (df["UNIT_MULT"].astype(int) == 0).all():
        raise ValueError("Unexpected population unit multiplier.")

    df["year"] = df["TIME_PERIOD"].astype(int)
    df["population"] = pd.to_numeric(
        df["OBS_VALUE"]
    ).astype("Int64")

    if df["year"].duplicated().any():
        raise ValueError("Duplicate MCP observation years.")

    return df.set_index("year")["population"].sort_index()


# 5. Execute all test cases
async def run_tests():
    s3_data = load_s3_data()
    failures = 0

    for case in TEST_CASES:
        print(f"\n--- {case['name']} ---")

        try:
            # Retrieve reference observations
            reference = get_s3_series(
                s3_data, case["country"]
            )

            years = case["years"]

            # Test 1: automatically select the latest
            # non-null year in our S3 reference.
            if years is None:
                years = [int(reference.dropna().index.max())]

            expected = reference.reindex(years)

            if expected.isna().any():
                raise ValueError("S3 reference has missing values.")

            # Let Qwen select and call MCP tools
            result = await answer_question(case["question"])

            # Extract the actual MCP observations
            actual = get_mcp_series(
                result["data_responses"],
                case["country"]
            )

            # Compare year indexes AND numerical values
            pd.testing.assert_series_equal(
                actual,
                expected.sort_index()
            )

            print("PASS")
            print(actual.to_string())

        except Exception as error:
            failures += 1
            print(f"FAIL: {type(error).__name__}: {error}")

    print(f"\nResults: {len(TEST_CASES) - failures}/3 passed")

    if failures:
        raise SystemExit(f"{failures} tests failed.")


if __name__ == "__main__":
    asyncio.run(run_tests())
