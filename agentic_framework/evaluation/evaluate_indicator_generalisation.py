
"""Evaluate agent generalization on three unseen WDI indicators."""

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


# Fixed evaluation cases. Do not tune prompts against these.
CASES = [
    {
        "id": "life_expectancy",
        "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country": "EGY",
        "start_year": 2000,
        "end_year": 2023,
        "question": (
            "List Egypt's life expectancy at birth, total "
            "(years), annually from 2000 through 2023. "
            "Return only year and value columns, ordered "
            "by year ascending."
        ),
    },
    {
        "id": "co2_emissions",
        "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5",
        "country": "FRA",
        "start_year": 2000,
        "end_year": 2023,
        "question": (
            "List France's CO2 emissions from fossil fuels "
            "and cement production in metric tons per capita, "
            "annually from 2000 through 2023. "
            "Return only year and value columns, ordered "
            "by year ascending."
        ),
    },
    {
        "id": "unemployment",
        "indicator_id": "WB_WDI_SL_UEM_TOTL_ZS",
        "country": "CHE",
        "start_year": 2010,
        "end_year": 2023,
        "question": (
            "List Switzerland's total unemployment rate "
            "(modeled ILO estimate, percent of total labor "
            "force), annually from 2010 through 2023. "
            "Return only year and value columns, ordered "
            "by year ascending."
        ),
    },
]


async def retrieve_reference(case):
    """Retrieve reference data directly from MCP without main.py."""

    records = []
    offset = 0

    async with Client(MCP_URL) as client:
        for _ in range(100):
            page = await call_data360_tool(
                client,
                "data360_get_data",
                {
                    "database_id": "WB_WDI",
                    "indicator_id": case["indicator_id"],
                    "country_code": case["country"],
                    "start_year": case["start_year"],
                    "end_year": case["end_year"],
                    "limit": 100,
                    "offset": offset,
                    "ref_area_filter": "none",
                },
            )

            records.extend(page["data"])

            if not page.get("has_more", False):
                break

            next_offset = page.get("next_offset")

            assert isinstance(next_offset, int)
            assert next_offset > offset
            offset = next_offset

        else:
            raise AssertionError("Reference pagination incomplete.")

        metadata = await call_data360_tool(
            client,
            "data360_get_metadata",
            {
                "database_id": "WB_WDI",
                "indicator_id": case["indicator_id"],
                "required_country": case["country"],
            },
        )

    return records, metadata


def build_reference(records, case):
    """Independently convert MCP observations using pandas."""

    assert records, "MCP returned no observations."

    df = pd.DataFrame(records)

    assert df["REF_AREA"].eq(case["country"]).all()

    if "INDICATOR" in df.columns:
        assert df["INDICATOR"].eq(case["indicator_id"]).all()

    if "UNIT_MULT" in df.columns:
        multipliers = pd.to_numeric(
            df["UNIT_MULT"], errors="raise"
        )
        assert multipliers.eq(0).all()

    df["year"] = pd.to_numeric(
        df["TIME_PERIOD"], errors="raise"
    ).astype(int)

    df["value"] = pd.to_numeric(
        df["OBS_VALUE"], errors="raise"
    )

    assert df["year"].between(
        case["start_year"], case["end_year"]
    ).all()

    assert not df["year"].duplicated().any()

    return (
        df[["year", "value"]]
        .sort_values("year")
        .reset_index(drop=True)
    )


def normalize_result(df):
    """Prepare a query result for numerical comparison."""

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["year", "value"]

    result = df.copy()
    result["year"] = pd.to_numeric(
        result["year"], errors="raise"
    ).astype(int)

    result["value"] = pd.to_numeric(
        result["value"], errors="raise"
    )

    assert not result["year"].duplicated().any()

    return result.sort_values("year").reset_index(drop=True)


def canonical_records(records):
    """Compare complete source records independently of row order."""

    return sorted(
        json.dumps(record, sort_keys=True, default=str)
        for record in records
    )


@pytest.mark.skipif(
    os.getenv("RUN_GENERALISATION_TESTS") != "1",
    reason="Live evaluation requires explicit opt-in.",
)
@pytest.mark.parametrize(
    "case",
    CASES,
    ids=[case["id"] for case in CASES],
)
def test_indicator_generalisation(case, monkeypatch):

    # Enable raw and normalized S3 persistence.
    monkeypatch.setenv("AGENT_SKIP_S3", "0")

    print(f"\n=== Evaluating: {case['id']} ===")

    # --------------------------------------------------
    # 1. Independent MCP reference retrieval
    # --------------------------------------------------

    reference_records, reference_metadata = asyncio.run(
        retrieve_reference(case)
    )

    assert (
        reference_metadata["indicator_metadata"]["idno"]
        == case["indicator_id"]
    )

    reference_df = build_reference(
        reference_records, case
    )

    # --------------------------------------------------
    # 2. Run the complete agentic pipeline
    # --------------------------------------------------

    outcome = asyncio.run(
        answer_question(case["question"])
    )

    selection = outcome["selection"]

    assert selection["database_id"] == "WB_WDI"
    assert selection["indicator_id"] == case["indicator_id"]
    assert selection["country_code"] == case["country"]
    assert selection["start_year"] == case["start_year"]
    assert selection["end_year"] == case["end_year"]

    # --------------------------------------------------
    # 3. Compare DuckDB SQL output with Python reference
    # --------------------------------------------------

    sql_df = normalize_result(outcome["results"])

    pd.testing.assert_frame_equal(
        sql_df,
        reference_df,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-6,
    )

    print("PASS: SQL results match independent MCP reference")

    # --------------------------------------------------
    # 4. Compare persisted raw S3 data with live MCP
    # --------------------------------------------------

    s3 = boto3.client(
        "s3", region_name=AWS_REGION
    )

    prefix = outcome["s3_prefix"]
    assert prefix is not None

    raw_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/raw.json",
    )

    raw_data = json.loads(
        raw_object["Body"].read()
    )

    assert raw_data["has_more"] is False

    assert canonical_records(
        raw_data["data"]
    ) == canonical_records(reference_records)

    reconstructed = [
        record
        for page in raw_data["raw_pages"]
        for record in page["data"]
    ]

    assert canonical_records(reconstructed) == canonical_records(
        raw_data["data"]
    )

    print("PASS: S3 raw observations match independent MCP")

    # --------------------------------------------------
    # 5. Compare normalized Parquet with Python reference
    # --------------------------------------------------

    parquet_object = s3.get_object(
        Bucket=S3_BUCKET,
        Key=f"{prefix}/observations.parquet",
    )

    parquet_df = pd.read_parquet(
        BytesIO(parquet_object["Body"].read())
    )

    assert parquet_df["indicator_id"].eq(
        case["indicator_id"]
    ).all()

    assert parquet_df["country_iso3"].eq(
        case["country"]
    ).all()

    parquet_values = normalize_result(
        parquet_df[["year", "value"]]
    )

    pd.testing.assert_frame_equal(
        parquet_values,
        reference_df,
        check_dtype=False,
        check_exact=False,
        rtol=1e-9,
        atol=1e-6,
    )

    print("PASS: Parquet matches independent Python reference")

    # --------------------------------------------------
    # 6. Check metadata persistence
    # --------------------------------------------------

    stored_metadata = json.loads(
        s3.get_object(
            Bucket=S3_BUCKET,
            Key=f"{prefix}/metadata.json",
        )["Body"].read()
    )

    assert (
        stored_metadata["indicator_metadata"]["idno"]
        == case["indicator_id"]
    )

    indicators_df = pd.read_parquet(
        BytesIO(
            s3.get_object(
                Bucket=S3_BUCKET,
                Key=f"{prefix}/indicators.parquet",
            )["Body"].read()
        )
    )

    assert len(indicators_df) == 1
    assert (
        indicators_df.iloc[0]["indicator_id"]
        == case["indicator_id"]
    )

    # --------------------------------------------------
    # 7. Evaluation summary
    # --------------------------------------------------

    unit = reference_metadata[
        "indicator_metadata"
    ]["measurement_unit"]

    print("\nEVALUATION PASSED")
    print("Indicator:", case["indicator_id"])
    print("Unit:", unit)
    print("Observations:", len(reference_df))
    print("First year:", int(reference_df["year"].min()))
    print("Last year:", int(reference_df["year"].max()))
    print("\nGenerated SQL:")
    print(outcome["sql"])


if __name__ == "__main__":
    raise SystemExit(
        pytest.main(["-v", "-s", __file__])
    )
