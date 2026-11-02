import pandas as pd
import pytest

from dash_app.ui import create_population_globe


def test_create_population_globe_uses_codes_and_log_population():
    records = pd.DataFrame(
        [
            {
                "country": "Country A",
                "country_iso3": " aaa ",
                "date": 2025,
                "population": 100,
            },
            {
                "country": "Country B",
                "country_iso3": "BBB",
                "date": 2025,
                "population": 10_000,
            },
        ]
    )
    original_records = records.copy(deep=True)

    fig = create_population_globe(records, year=2025)

    # The figure receives normalised codes and log10 population values.
    assert list(fig.data[0].locations) == ["AAA", "BBB"]
    assert list(fig.data[0].z) == pytest.approx([2, 4])

    # Creating the figure must not change the caller's DataFrame.
    pd.testing.assert_frame_equal(records, original_records)


from dash_app.ui import create_population_history_chart


def test_create_population_history_chart():
    history = pd.DataFrame(
        [
            {"country": "Egypt", "date": 2020, "population": 100},
            {"country": "Egypt", "date": 2021, "population": 105},
        ]
    )

    fig = create_population_history_chart(history)

    assert list(fig.data[0].x) == [2020, 2021]
    assert list(fig.data[0].y) == [100, 105]
    assert "Egypt" in fig.layout.title.text