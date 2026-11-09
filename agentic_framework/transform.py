
import pandas as pd


def normalize_observations(
    mcp_response: dict,
    indicator_id: str
) -> pd.DataFrame:
    """
    Normalize annual country-level Data360 observations
    into our standard analytical schema.
    """

    if mcp_response.get("error"):
        raise ValueError(mcp_response["error"])

    if mcp_response.get("has_more"):
        raise ValueError(
            "Retrieve all MCP pages before transforming."
        )

    records = mcp_response.get("data", [])

    if not records:
        raise ValueError("No observations returned.")

    df = pd.DataFrame(records)

    required = {
        "REF_AREA",
        "TIME_PERIOD",
        "OBS_VALUE",
        "UNIT_MULT",
    }

    if not required.issubset(df.columns):
        raise ValueError("Missing required observation fields.")

    # Initially support only unscaled annual observations.
    if not (df["UNIT_MULT"].astype(int) == 0).all():
        raise ValueError(
            "Unit multiplier conversion is not implemented."
        )

    normalized = pd.DataFrame({
        "indicator_id": indicator_id,
        "country_iso3": df["REF_AREA"],
        "year": pd.to_numeric(df["TIME_PERIOD"]),
        "value": pd.to_numeric(df["OBS_VALUE"]),
    })

    normalized["year"] = normalized["year"].astype(int)

    if normalized.duplicated(
        ["indicator_id", "country_iso3", "year"]
    ).any():
        raise ValueError(
            "Duplicate observations or additional dimensions detected."
        )

    return normalized
