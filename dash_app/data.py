import json
import boto3
import pandas as pd
from botocore.exceptions import BotoCoreError, ClientError


class PopulationDataLoadError(Exception):
    """Raised when population data cannot be read from S3."""


def load_population_data(bucket_name, object_key, s3_client):
    """Read population records from S3 and return a DataFrame."""
    try:
        response = s3_client.get_object(
            Bucket=bucket_name,
            Key=object_key,
        )
        contents = response["Body"].read()
    except (BotoCoreError, ClientError) as error:
        raise PopulationDataLoadError(
            "Could not load population data from S3."
        ) from error

    records = json.loads(contents)
    return pd.DataFrame(records)