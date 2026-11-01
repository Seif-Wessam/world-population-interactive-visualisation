import json
import urllib.request
from datetime import date
from urllib.parse import urlencode

BUCKET = "webgis-population-app"

def get_all_world_bank_pages(base_url, parameters):
    """Fetch every page of a World Bank response.

    Returns the first page's metadata and a combined list of records.
    Raises an error if a request fails or the response is incomplete.
    """
    all_records = []
    first_metadata = None
    expected_pages = None
    expected_total = None
    page = 1

    while expected_pages is None or page <= expected_pages:
        page_parameters = {
            **parameters,
            "page": page,
        }

        request_url = f"{base_url}?{urlencode(page_parameters)}"

        with urllib.request.urlopen(request_url, timeout=30) as response:
            data = json.loads(response.read())

        # A valid response for these requests should be [metadata, records].
        if (
            not isinstance(data, list)
            or len(data) != 2
            or not isinstance(data[0], dict)
            or not isinstance(data[1], list)
        ):
            raise ValueError(
                f"Unexpected World Bank response for page {page}."
            )

        metadata, records = data

        if page == 1:
            first_metadata = metadata
            expected_pages = int(metadata["pages"])
            expected_total = int(metadata["total"])

            if expected_pages < 1:
                raise ValueError("World Bank returned no pages.")

        # Detect an unexpected page or changing pagination metadata.
        if (
            int(metadata["page"]) != page
            or int(metadata["pages"]) != expected_pages
            or int(metadata["total"]) != expected_total
        ):
            raise ValueError(
                f"Inconsistent World Bank metadata on page {page}."
            )

        all_records.extend(records)
        page += 1

    if len(all_records) != expected_total:
        raise ValueError(
            "Incomplete World Bank response: "
            f"expected {expected_total} records, received {len(all_records)}."
        )

    return first_metadata, all_records


def get_population_data_and_country_metadata():
    current_year = date.today().year

    population_url = (
        "https://api.worldbank.org/v2/country/all/"
        "indicator/SP.POP.TOTL"
    )

    _, population_records = get_all_world_bank_pages(
        population_url,
        {
            "format": "json",
            "per_page": 3000,
            "date": f"1970:{current_year}",
        },
    )

    records_list = []
    for record in population_records:
        record_dict = {
            "country": record["country"]["value"],
            "country_id": record["country"]["id"],
            "date": record["date"],
            "population": record["value"],
            "country_iso3": record["countryiso3code"],
        }
        records_list.append(record_dict)

    metadata_url = "https://api.worldbank.org/v2/country"

    metadata, country_records = get_all_world_bank_pages(
        metadata_url,
        {
            "format": "json",
            "per_page": 3000,
        },
    )

    # Keep the response shape expected by the enrichment function.
    country_metadata = [metadata, country_records]

    return records_list, country_metadata

    
def enrich_population_records_with_country_info(population_records, country_metadata):

    #create a lookup dictionary for country and region information
    country_and_region_lookup = {}
    for country in country_metadata[1]:
        country_id = country.get('iso2Code')
        country_and_region_lookup[country_id] = {
            "name": country.get('name'),
            "region": country.get('region', {}).get('value'),
            "is_aggregate": country.get('region', {}).get('id') == "NA"
        }

    #fill the records_list with the region and is_aggregate information
    for record in population_records:
        country_id = record.get('country_id')
        if country_id in country_and_region_lookup:
            record['region'] = country_and_region_lookup[country_id]['region']
            record['is_aggregate'] = country_and_region_lookup[country_id]['is_aggregate']
        else:
            record['region'] = None
            record['is_aggregate'] = None

    return population_records


def s3_write_to_bucket(data, bucket_name, key):
    import boto3
    s3 = boto3.client("s3")
    serialised_data = json.dumps(data)
    response = s3.put_object(
        Bucket=bucket_name, 
        Key=key, 
        Body=serialised_data, 
        ContentType='application/json')
    return serialised_data, response["ResponseMetadata"]["HTTPStatusCode"]


def lambda_handler(event, context):
    population_records, country_metadata = (
        get_population_data_and_country_metadata()
    )

    enriched_records = enrich_population_records_with_country_info(
        population_records,
        country_metadata,
    )

    # This is called only after retrieval and enrichment succeed.
    serialised_data, status_code = s3_write_to_bucket(
        enriched_records,
        BUCKET,
        "data/enriched_population_data.json",
    )

    summary = {
        "message": "Population data written to S3.",
        "record_count": len(enriched_records),
        "json_size_bytes": len(serialised_data.encode("utf-8")),
    }

    return {
        "statusCode": status_code,
        "body": json.dumps(summary),
    }

if __name__ == "__main__":
    lambda_handler(None, None)

