import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from dash_app.data import get_country_history, prepare_population_data


def test_prepare_population_data_converts_years_to_integers():
    data = pd.DataFrame(
        {
            "country_iso3": ["FRA", "FRA"],
            "date": ["2020", "1970"],
            "population": [67000000, None],
            "is_aggregate": [False, False],
        }
    )

    result = prepare_population_data(data)

    assert result["date"].tolist() == [2020, 1970]
    assert pd.api.types.is_integer_dtype(result["date"])


def test_prepare_population_data_rejects_invalid_year():
    data = pd.DataFrame(
        {
            "country_iso3": ["FRA"],
            "date": ["not-a-year"],
            "population": [67000000],
            "is_aggregate": [False],
        }
    )

    with pytest.raises(ValueError):
        prepare_population_data(data)


def test_get_country_history_filters_and_sorts_records():
    data = pd.DataFrame(
        {
            "country_iso3": ["FRA", "EGY", "FRA", "FRA"],
            "date": [2020, 1970, 1970, 1980],
            "population": [67000000, 35000000, None, 54000000],
            "is_aggregate": [False, False, False, True],
        }
    )

    result = get_country_history(data, "FRA")

    expected = data.loc[[2, 0]].sort_values("date")

    assert_frame_equal(result, expected)
    assert pd.isna(result.iloc[0]["population"])


def test_get_country_history_returns_empty_when_no_country_matches():
    data = pd.DataFrame(
        {
            "country_iso3": ["FRA"],
            "date": [2020],
            "population": [67000000],
            "is_aggregate": [False],
        }
    )

    result = get_country_history(data, "EGY")

    assert result.empty