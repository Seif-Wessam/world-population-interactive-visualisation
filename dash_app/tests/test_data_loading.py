import io

import pandas as pd
import pytest
from botocore.exceptions import ClientError
from pandas.testing import assert_frame_equal

from dash_app.data import PopulationDataLoadError, load_population_data


class FakeS3Client:
    def get_object(self, Bucket, Key):
        assert Bucket == "test-bucket"
        assert Key == "population.json"

        return {
            "Body": io.BytesIO(
                b'[{"country": "France", "population": 68000000}]'
            )
        }


class FailingS3Client:
    def get_object(self, Bucket, Key):
        raise ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "Access denied"}},
            "GetObject",
        )


def test_load_population_data_returns_dataframe():
    result = load_population_data(
        "test-bucket",
        "population.json",
        FakeS3Client(),
    )

    expected = pd.DataFrame(
        [{"country": "France", "population": 68000000}]
    )

    assert_frame_equal(result, expected)


def test_load_population_data_raises_error_when_s3_fails():
    with pytest.raises(
        PopulationDataLoadError,
        match="Could not load population data from S3",
    ) as error_info:
        load_population_data(
            "test-bucket",
            "population.json",
            FailingS3Client(),
        )

    assert isinstance(error_info.value.__cause__, ClientError)