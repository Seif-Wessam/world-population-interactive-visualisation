from ingestion.lambda_function import enrich_population_records_with_country_info, get_population_data_and_country_metadata
import io
import json
from unittest.mock import patch

def test_enrich_population_records_with_country_info():
    # Sample population records
    population_records = [
        {"country": "Country A", "country_id": "A", "date": "2020", "population": 1000},
        {"country": "Country B", "country_id": "B", "date": "2020", "population": 2000},
        {"country": "Country C", "country_id": "C", "date": "2020", "population": 3000}
    ]

    # Sample country metadata
    country_metadata = [
        {},
        [
            {"iso2Code": "A", "name": "Country A", "region": {"id": "1", "value": "Region 1"}},
            {"iso2Code": "B", "name": "Country B", "region": {"id": "NA", "value": None}},
            {"iso2Code": "C", "name": "Country C", "region": {"id": "2", "value": "Region 2"}}
        ]
    ]

    # Enrich the population records with country info
    enriched_records = enrich_population_records_with_country_info(population_records, country_metadata)

    # Expected results
    expected_records = [
        {"country": "Country A", "country_id": "A", "date": "2020", 
         "population": 1000, "region": "Region 1", 
         "is_aggregate": False},
        {"country": "Country B", "country_id": "B", 
         "date": "2020", 
         "population": 2000, 
         "region": None, 
         "is_aggregate": True},
        {"country": "Country C", 
         "country_id": "C", 
         "date": "2020", 
         "population": 3000, 
         "region": 'Region 2', 
         'is_aggregate': False}
    ]

    assert enriched_records == expected_records


def test_population_data_preserves_country_iso3():
    population_response = [
        {"page": 1, "pages": 1, "total": 1},
        [
            {
                "country": {"id": "FR", "value": "France"},
                "countryiso3code": "FRA",
                "date": "2025",
                "value": 68000000,
            }
        ],
    ]

    metadata_response = [
        {"page": 1, "pages": 1, "total": 1},
        [{"iso2Code": "FR"}],
    ]

    fake_responses = [
        io.BytesIO(json.dumps(population_response).encode("utf-8")),
        io.BytesIO(json.dumps(metadata_response).encode("utf-8")),
    ]

    with patch(
        "ingestion.lambda_function.urllib.request.urlopen",
        side_effect=fake_responses,
    ):
        records, _ = get_population_data_and_country_metadata()

    assert records[0]["country"] == "France"
    assert records[0]["country_id"] == "FR"
    assert records[0]["country_iso3"] == "FRA"

