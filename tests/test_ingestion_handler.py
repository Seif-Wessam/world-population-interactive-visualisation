import json
from unittest.mock import Mock

import ingestion.lambda_function as ingestion


def test_handler_writes_records_and_returns_summary(monkeypatch):
    # Arrange: a small set of enriched records.
    records = [
        {
            "country": "Côte d'Ivoire",
            "country_id": "CI",
            "country_iso3": "CIV",
            "date": "2020",
            "population": 26378274,
            "region": "Sub-Saharan Africa",
            "is_aggregate": False,
        }
    ]

    # Use non-ASCII characters to check that the size is counted in bytes.
    serialised_data = json.dumps(records, ensure_ascii=False)

    fake_retrieval = Mock(return_value=(records, [{}, []]))
    fake_enrichment = Mock(return_value=records)
    fake_writer = Mock(return_value=(serialised_data, 200))

    monkeypatch.setattr(
        ingestion,
        "get_population_data_and_country_metadata",
        fake_retrieval,
    )
    monkeypatch.setattr(
        ingestion,
        "enrich_population_records_with_country_info",
        fake_enrichment,
    )
    monkeypatch.setattr(
        ingestion,
        "s3_write_to_bucket",
        fake_writer,
    )

    # Act.
    response = ingestion.lambda_handler(None, None)

    # Assert that the writer received the enriched data.
    fake_writer.assert_called_once_with(
        records,
        ingestion.BUCKET,
        "data/enriched_population_data.json",
    )

    # Assert that the handler returns a compact, accurate summary.
    summary = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert summary["record_count"] == 1
    assert summary["json_size_bytes"] == len(
        serialised_data.encode("utf-8")
    )