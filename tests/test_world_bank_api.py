import io
import json
from unittest.mock import Mock
from urllib.error import URLError
from urllib.parse import parse_qs, urlparse
import pytest
import ingestion.lambda_function as ingestion
from unittest.mock import patch
from ingestion.lambda_function import get_all_world_bank_pages


def test_get_all_world_bank_pages_combines_two_pages():
    page_1 = [
        {"page": 1, "pages": 2, "total": 3},
        [{"id": "A"}, {"id": "B"}],
    ]

    page_2 = [
        {"page": 2, "pages": 2, "total": 3},
        [{"id": "C"}],
    ]

    responses = [
        io.BytesIO(json.dumps(page_1).encode("utf-8")),
        io.BytesIO(json.dumps(page_2).encode("utf-8")),
    ]

    with patch(
        "ingestion.lambda_function.urllib.request.urlopen",
        side_effect=responses,
    ):
        metadata, records = get_all_world_bank_pages(
            "https://example.test/data",
            {"format": "json", "per_page": 2},
        )

    assert metadata["pages"] == 2
    assert records == [
        {"id": "A"},
        {"id": "B"},
        {"id": "C"},
    ]


@pytest.mark.parametrize("failed_page", [1, 2])
def test_failed_population_page_does_not_write_to_s3(
    monkeypatch, failed_page
):
    requested_pages = []

    def fake_urlopen(url, timeout):
        # Read the page number from the URL requested by the helper.
        query = parse_qs(urlparse(url).query)
        page = int(query["page"][0])
        requested_pages.append(page)

        if page == failed_page:
            raise URLError(f"Simulated failure on page {page}")

        # If page 1 succeeds, tell the helper that page 2 also exists.
        response = [
            {"page": 1, "pages": 2, "total": 2},
            [{"example": "page 1 record"}],
        ]
        return io.BytesIO(json.dumps(response).encode("utf-8"))

    fake_s3_writer = Mock()

    # Replace the real network request and S3 writer for this test.
    monkeypatch.setattr(
        ingestion.urllib.request, "urlopen", fake_urlopen
    )
    monkeypatch.setattr(
        ingestion, "s3_write_to_bucket", fake_s3_writer
    )

    with pytest.raises(URLError, match=f"page {failed_page}"):
        ingestion.lambda_handler(None, None)

    assert requested_pages == list(range(1, failed_page + 1))
    fake_s3_writer.assert_not_called()


@pytest.mark.parametrize("failed_page", [1, 2])
def test_failed_metadata_page_does_not_write_to_s3(
    monkeypatch, failed_page
):
    requested_metadata_pages = []

    def fake_urlopen(url, timeout):
        parsed_url = urlparse(url)
        query = parse_qs(parsed_url.query)
        page = int(query["page"][0])

        if parsed_url.path.endswith("/indicator/SP.POP.TOTL"):
            # Population retrieval succeeds.
            response = [
                {"page": 1, "pages": 1, "total": 1},
                [
                    {
                        "country": {"id": "FR", "value": "France"},
                        "countryiso3code": "FRA",
                        "date": "2020",
                        "value": 68000000,
                    }
                ],
            ]

        elif parsed_url.path.endswith("/country"):
            requested_metadata_pages.append(page)

            if page == failed_page:
                raise URLError(
                    f"Simulated metadata failure on page {page}"
                )

            # Page 1 succeeds and indicates that a second page exists.
            response = [
                {"page": 1, "pages": 2, "total": 2},
                [
                    {
                        "iso2Code": "FR",
                        "region": {
                            "id": "ECS",
                            "value": "Europe & Central Asia",
                        },
                    }
                ],
            ]

        else:
            raise AssertionError(f"Unexpected API endpoint: {parsed_url.path}")

        return io.BytesIO(json.dumps(response).encode("utf-8"))

    fake_s3_writer = Mock()

    monkeypatch.setattr(
        ingestion.urllib.request, "urlopen", fake_urlopen
    )
    monkeypatch.setattr(
        ingestion, "s3_write_to_bucket", fake_s3_writer
    )

    with pytest.raises(
        URLError,
        match=f"metadata failure on page {failed_page}",
    ):
        ingestion.lambda_handler(None, None)

    assert requested_metadata_pages == list(
        range(1, failed_page + 1)
    )
    fake_s3_writer.assert_not_called()