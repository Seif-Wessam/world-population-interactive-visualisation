import pandas as pd


def normalize_observations(
    mcp_response: dict,
    indicator_id: str
) -> pd.DataFrame:
    """Normalize annual, country-level Data360 observations."""

    # 1. Check for unsuccessful or incomplete retrieval
    if mcp_response.get("error"):
        raise ValueError(mcp_response["error"])

    if mcp_response.get("has_more"):
        raise ValueError(
            "Retrieve all MCP pages before transforming."
        )

    records = mcp_response.get("data", [])

    if not isinstance(records, list) or not records:
        raise ValueError("Expected a non-empty list of observations.")

    df = pd.DataFrame(records)

    # 2. Verify source fields
    required = {
        "REF_AREA",
        "TIME_PERIOD",
        "OBS_VALUE",
        "UNIT_MEASURE",
    }

    missing = required - set(df.columns)

    if missing:
        raise ValueError(f"Missing fields: {sorted(missing)}")

    # 3. Reject unsupported disaggregations
    dimensions = [
        "SEX",
        "AGE",
        "URBANISATION",
        "COMP_BREAKDOWN_1",
        "COMP_BREAKDOWN_2",
        "COMP_BREAKDOWN_3",
    ]

    for dimension in dimensions:
        if dimension in df.columns:
            valid = df[dimension].isin(["_T", "_Z"]) | df[dimension].isna()

            if not valid.all():
                raise ValueError(
                    f"Unsupported disaggregation: {dimension}"
                )

    # 4. Support annual observations only
    if "FREQ" in df.columns:
        if not df["FREQ"].eq("A").all():
            raise ValueError("Only annual observations are supported.")

    # 5. Validate units and multipliers
    units = df["UNIT_MEASURE"].dropna().unique()

    if len(units) != 1:
        raise ValueError("Expected one consistent measurement unit.")

    if "UNIT_MULT" in df.columns:
        multipliers = pd.to_numeric(
            df["UNIT_MULT"], errors="raise"
        )

        if multipliers.isna().any() or not multipliers.eq(0).all():
            raise ValueError(
                "Unsupported or missing unit multiplier."
            )

    # 6. Verify the indicator identifier when supplied
    if "INDICATOR" in df.columns:
        if not df["INDICATOR"].eq(indicator_id).all():
            raise ValueError("Unexpected indicator in MCP observations.")

    # 7. Convert source fields to our analytical schema
    years = df["TIME_PERIOD"].astype(str)

    if not years.str.fullmatch(r"\d{4}").all():
        raise ValueError("Expected four-digit annual periods.")

    normalized = pd.DataFrame({
        "indicator_id": indicator_id,
        "country_iso3": df["REF_AREA"],
        "year": years.astype(int),
        "value": pd.to_numeric(
            df["OBS_VALUE"], errors="raise"
        ),
    })

    # 8. Reject invalid identifiers and duplicate observations
    if normalized["country_iso3"].isna().any():
        raise ValueError("Missing geographical identifiers.")

    if normalized.duplicated(
        ["indicator_id", "country_iso3", "year"]
    ).any():
        raise ValueError("Duplicate observations detected.")

    return normalized

def normalize_metadata(mcp_response: dict) -> pd.DataFrame:
    """Convert Data360 metadata into a standardized indicator row."""

    if mcp_response.get("error"):
        raise ValueError(mcp_response["error"])

    record = mcp_response.get("indicator_metadata")

    if not isinstance(record, dict):
        raise ValueError("Missing indicator_metadata.")

    required = [
        "idno",
        "database_id",
        "name",
        "measurement_unit",
        "periodicity",
    ]

    for field in required:
        if not record.get(field):
            raise ValueError(f"Missing metadata field: {field}")

    return pd.DataFrame([{
        "indicator_id": record["idno"],
        "database_id": record["database_id"],
        "name": record["name"],
        "unit": record["measurement_unit"],
        "definition": (
            record.get("definition_long")
            or record.get("definition_short")
        ),
        "periodicity": record["periodicity"],
    }])