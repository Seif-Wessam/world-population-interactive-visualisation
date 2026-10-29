# Population ingestion

This component retrieves the latest population observations and country metadata from the World Bank, enriches each observation, and writes the result to Amazon S3. It is deployed as an AWS Lambda container image.

## Data flow

1. Request population data and country metadata from the World Bank API.
2. Extract the list of population observations from the response.
3. Build simplified records and a metadata lookup keyed by `iso2Code`.
4. Match each observation's `country.id` to the lookup; add its region and aggregate flag.
5. Serialize the enriched records as JSON and upload them to S3.

The World Bank response contains individual economies and aggregate groups. The current classification marks an entry as an aggregate when the metadata region ID is `NA`. Economies can include territories as well as sovereign countries.

Example output record:

```json
{
  "country": "Africa Eastern and Southern",
  "country_id": "ZH",
  "date": "2025",
  "population": 788844284,
  "region": "Aggregates",
  "is_aggregate": true
}
```

A missing population is stored as JSON `null`. When a population record has no matching metadata, `region` and `is_aggregate` are `null`. Observation dates are strings. The output is written to the configured bucket under `data/enriched_population_data.json`; another successful run writes to the same key.

## Files

- `lambda_function.py`: API requests, transformation, S3 write, and Lambda handler.
- `requirements.txt`: runtime dependencies.
- `Dockerfile`: definition of the Lambda-compatible image.
- `../tests/test_population.py`: tests for the enrichment transformation.

## Run locally

From the repository root in PowerShell, install dependencies and run the tests:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

To run the complete ingestion locally, authenticate with AWS and select your profile:

```powershell
aws login --profile population-dev --region eu-north-1
$env:AWS_PROFILE = "population-dev"
python .\ingestion\lambda_function.py
```

This runs the handler and **writes to the S3 bucket configured in the code**. Your AWS identity needs permission to put an object there. The script does not print the handler's return value when run this way. Use an appropriately scoped development bucket when experimenting.

## Build and test the image locally

From the repository root, with Docker Desktop running:

```powershell
docker buildx build --platform linux/amd64 --provenance=false --load -t population-lambda:local ./ingestion
```

Start the local Lambda container:

```powershell
docker run --rm --name population-local --platform linux/amd64 -p 127.0.0.1:9000:8080 population-lambda:local
```

In a second PowerShell window, invoke it:

```powershell
$result = Invoke-RestMethod -Uri "http://localhost:9000/2015-03-31/functions/function/invocations" -Method Post -Body '{}' -ContentType 'application/json'
$result.statusCode
```

The current handler writes to S3, so this invocation also needs AWS credentials available **inside the container** and network access; local CLI login is not automatically inherited. The container can start without them, but an invocation requiring S3 may fail. Stop it with Ctrl+C in the first window.

## Deploy to AWS

1. Commit and push the intended code and dependency changes.
2. In GitHub, open **Actions → Deploy ingestion to dev → Run workflow** and select `main`.
3. Check that tests, AWS authentication, image build and upload, and Lambda update succeed.
4. Invoke the Lambda with a test event such as `{}`. Check the execution result and logs.
5. Check the S3 object's last-modified time and inspect its content.

The workflow builds from `ingestion/`, pushes a uniquely tagged image to ECR, and updates the existing Lambda. It does not invoke the function. GitHub uses OIDC to assume a deployment role configured via the `AWS_DEPLOY_ROLE_ARN` repository variable. The Lambda uses a separate execution role that needs permission to write to S3.

## Known limitations

- Both API requests currently request up to 300 records; pagination and completeness checks are not implemented.
- `mrv=1` retrieves the latest available observation per series, rather than historical time series; observation years can differ.
- A successful deployment does not by itself verify a successful invocation or S3 write.
- The current unit test checks enrichment with sample data; it does not test the live World Bank API or S3 integration.
- The bucket is currently configured in the Python code. Separate environment configuration is a future improvement.

Data source: [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/topics/125589-developer-information).
