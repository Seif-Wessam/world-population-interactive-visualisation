from lambda_function import enrich_population_records_with_country_info

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
