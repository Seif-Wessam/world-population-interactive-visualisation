
import asyncio
import json
import os
from io import BytesIO

import boto3
import pandas as pd
import pytest
from mcp import Client

from agentic_framework.main import (
    answer_question,
    S3_BUCKET,
    AWS_REGION,
)
from agentic_framework.mcp_client import (
    MCP_URL,
    call_data360_tool,
)


INDICATOR_ID = "WB_WDI_NY_GDP_PCAP_CD"
DATABASE_ID = "WB_WDI"
COUNTRY = "CHE"
START_YEAR = 2015
END_YEAR = 2023

QUESTION = (
    "List Switzerland's annual GDP per capita "
    "in current US dollars from 2015 through 2023. "
    "Return exactly two columns named year and value, "
    "one row per year, ordered by year ascending."
)


async def retrieve_reference_from_mcp():
    """
    Independently retrieve the World Bank source data.

    Do not use main.py or fetch_all_observations().
    Handle pagination directly inside the test.
    """

    records = []
    offset = 0

    async with Client(MCP_URL) as client:
        for _ in range(100):
            page = await call_data360_tool(
                client,
                "data360_get_data",
                {
                    "database_id": DATABASE_ID,
                    "indicator_id": INDICATOR_ID,
                    "country_code": COUNTRY,
                    "start_year": START_YEAR,
                    "end_year": END_YEAR,
                    "limit": 100,
                    "offset": offset,
                    "ref_area_filter": "none",
                },
            )

            records.extend(page["data"])

            if not page.get("has_more", False):
                break

            next_offset = page.get("next_offset")

            if (
                not isinstance(next_offset, int)
                or next_offset <= offset
            ):
                raise AssertionError(
                    "Invalid reference pagination."
                )

            offset = next_offset

        else:
            raise AssertionError(
                "Reference retrieval exceeded 100 pages."
            )

    return records


def build_python_reference(records):
    """
    Independently transform and analyze MCP observations
    using pandas, without transform.py or DuckDB.
    """

    df = pd.DataFrame(records)

    assert not df.empty

    assert df["REF_AREA"].eq(COUNTRY).all()

    if "INDICATOR" in df.columns:
        assert df["INDICATOR"].eq(INDICATOR_ID).all()

    df["year"] = df["TIME_PERIOD"].astype(int)
    df["value"] = pd.to_numeric(
        df["OBS_VALUE"],
        errors="raise",
    )

    assert df["year"].between(
        START_YEAR, END_YEAR
    ).all()

    assert not df["year"].duplicated().any()

    reference_df = (
        df[["year", "value"]]
        .sort_values("year")
        .reset_index(drop=True)
    )

    assert reference_df["year"].tolist() == list(
        range(START_YEAR, END_YEAR + 1)
    )

    return reference_df


def canonical_records(records):
    """
    Compare raw observations independently of row order.

    Preserve all record fields, not only year and value.
    """

    return sorted(
        json.dumps(
            record,
            sort_keys=True,
            default=str,
        )
        for record in records
    )


@pytest.mark.skipif(
    os.getenv("RUN_LIVE_AGENT_TEST") != "1",
    reason="Requires real MCP, Qwen and AWS access.",
)
def test_main_end_to_end(monkeypatch):

    monkeypatch.setenv("AGENT_SKIP_S3", "0")

    # --------------------------------------------------
    # STEP 1: Independently retrieve data from MCP
    # --------------------------------------------------

    reference_records = asyncio.run(
        retrieve_reference_from_mcp()
    )

    assert len(reference_records) == 9

    # --------------------------------------------------
    # STEP 2: Calculate the reference using Python
    # --------------------------------------------------

    reference_df = build_python_reference(
        reference_records
    )

    reference_values = reference_df.set_index("year")[
        "value"
    ]

    reference_change = (
        reference_values.loc[2023]
        - reference_values.loc[2015]
    )

    reference_pct_change = (
        reference_change / reference_values.loc[2015]
    ) * 100

    print("\nPYTHON REFERENCE:")
    print(reference_df.to_string(index=False))

    print(
        "Reference absolute change:",
        reference_change,
    )

    print(
        "Reference percentage change:",
        reference_pct_change,
    )

    # --------------------------------------------------
    # STEP 3: Run our complete agentic pipeline
    # --------------------------------------------------

    outcome = asyncio.run(
        answer_question(QUESTION)
    )

    selection = outcome["selection"]

    assert selection == {
        "database_id": DATABASE_ID,
        "indicator_id": INDICATOR_ID,
        "country_code": COUNTRY,
        "start_year": START_YEAR,
        "end_year": END_YEAR,
    }

    assert 'CREATE TABLE "observations"' in outcome["schema"]
    assert 'CREATE TABLE "indicators"' in outcome["schema"]

    # --------------------------------------------------
    # STEP 4: Compare SQL results with Python reference
    # --------------------------------------------------

    sql_df = outcome["results"].copy()

    assert list(sql_df.columns) == ["year", "value"]

    sql_df["year"] = sql_df["year"].astype(int)
    sql_df["value"] = pd.to_numeric(
        sql_df["value"],
        errors="raise",
    )

    # Require ascending order, as requested.
    assert sql_df["year"].tolist() == list(
        range(START_YEAR, END_YEAR + 1)
    )

    pd.testing.assert_frame_equal(
        sql_df.reset_index(drop=True),
        reference_df,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-6,
    )

    print("\nSQL RESULTS MATCH PYTHON REFERENCE.")

    # Independently compare the numerical calculation.
    sql_values = sql_df.set_index("year")["value"]

    sql_change = (
        sql_values.loc[2023]
        - sql_values.loc[2015]
    )

    assert sql_change == pytest.approx(
        reference_change,
        rel=1e-9,
        abs=1e-6,
    )

    # --------------------------------------------------
    # STEP 5: Read the raw data stored in S3
    # --------------------------------------------------

    s3 = boto3.client(
        "s3",
        region_name=AWS_REGION,
    )

    prefix = outcome["s3_prefix"]
    assert prefix is not None

    raw_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/raw.json",
    )

    s3_raw_data = json.loads(
        raw_object["Body"].read()
    )

    assert s3_raw_data["has_more"] is False

    s3_records = s3_raw_data["data"]

    # --------------------------------------------------
    # STEP 6: Compare raw S3 with independent MCP data
    # --------------------------------------------------

    assert len(s3_records) == len(reference_records)

    assert canonical_records(
        s3_records
    ) == canonical_records(
        reference_records
    )

    # Also verify that stored pages reconstruct the data.
    reconstructed = [
        record
        for page in s3_raw_data["raw_pages"]
        for record in page["data"]
    ]

    assert canonical_records(
        reconstructed
    ) == canonical_records(s3_records)

    print("\nRAW S3 OBSERVATIONS MATCH LIVE MCP DATA.")

    # --------------------------------------------------
    # STEP 7: Verify normalized Parquet saved to S3
    # --------------------------------------------------

    parquet_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/observations.parquet",
    )

    parquet_df = pd.read_parquet(
        BytesIO(parquet_object["Body"].read())
    )

    assert parquet_df["indicator_id"].eq(
        INDICATOR_ID
    ).all()

    assert parquet_df["country_iso3"].eq(
        COUNTRY
    ).all()

    parquet_reference = (
        parquet_df[["year", "value"]]
        .sort_values("year")
        .reset_index(drop=True)
    )

    pd.testing.assert_frame_equal(
        parquet_reference,
        reference_df,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-6,
    )

    # --------------------------------------------------
    # STEP 8: Verify indicator metadata persistence
    # --------------------------------------------------

    metadata_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/metadata.json",
    )

    metadata = json.loads(
        metadata_object["Body"].read()
    )

    assert metadata["indicator_metadata"]["idno"] == INDICATOR_ID
    assert metadata["indicator_metadata"]["database_id"] == DATABASE_ID

    indicators_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/indicators.parquet",
    )

    indicators_df = pd.read_parquet(
        BytesIO(indicators_object["Body"].read())
    )

    assert len(indicators_df) == 1
    assert indicators_df.iloc[0]["indicator_id"] == INDICATOR_ID
    assert indicators_df.iloc[0]["database_id"] == DATABASE_ID

    # --------------------------------------------------
    # STEP 9: Final verification
    # --------------------------------------------------

    print("\nALL INTEGRATION CHECKS PASSED.")
    print("Indicator:", INDICATOR_ID)
    print("Country:", COUNTRY)
    print("Observations:", len(reference_records))
    print("Absolute change:", reference_change)
    print("Percentage change:", reference_pct_change)
    print("\nGenerated SQL:")
    print(outcome["sql"])
