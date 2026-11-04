# Population dashboard

An interactive Dash and Plotly application for exploring historical
World Bank population data stored in Amazon S3.

**Status:** implemented and run locally. AWS dashboard deployment is pending.

## Interface

The application contains two main panels:

- **Globe:** a rotatable world map with a vertical Viridis population scale
  on the left.
- **Country details:** an initially empty panel that displays the selected
  economy's name, latest available population, observation year and
  historical line chart.

Selecting another economy updates the details panel. Clear selection
restores the empty state and clears the stored click selection, allowing
the same economy to be selected again.

The selection callback does not replace the globe figure. A stable
`uirevision` is also configured to preserve the globe's interaction state.

CSS defines a side-by-side desktop layout and stacks the panels on
smaller screens. Browser checks are still needed when changing graph
dimensions or container styling.

## Data flow

1. The ingestion pipeline writes enriched population JSON to S3.
2. On application startup, the backend reads the object using Boto3.
3. The records are converted into a pandas DataFrame.
4. Observation years are converted to integers.
5. Eligible economy records are selected for the globe.
6. Dash callbacks retrieve the selected economy's history from the
   in-memory DataFrame.

Country clicks do not trigger new World Bank API requests or S3 downloads.

The dataset is loaded once per application process. Restart the local app
after ingestion to load a new snapshot.

See [the ingestion guide](../ingestion/README.md) for how the dataset is
retrieved and enriched.

## Map and chart behaviour

### Globe

The map uses the latest year with population values and non-empty ISO3
codes for more than 200 distinct economies.

Records must have `is_aggregate == False`. Records with missing population
values or empty ISO3 codes are excluded from map selection.

Colour represents the base-10 logarithm of population using Viridis.
The legend labels show population magnitudes, while hover information
shows the actual population and observation year.

Non-positive population values are not assigned a logarithmic colour.
Some provider codes may not match a geometry supported by Plotly.

### Country details

The details panel displays the selected economy's most recent non-missing
population observation.

That observation year may differ from the globe's year. The panel labels
its own year explicitly.

The historical chart displays available records in chronological order
with a fixed dark-purple line. Missing population values remain missing;
they are not replaced with zero.

If no usable history is available, the panel displays a message.

## Files

| File | Responsibility |
| --- | --- |
| `app.py` | S3 loading, map-year selection and application assembly |
| `data.py` | S3 reading, year conversion and history filtering |
| `layout.py` | Component layout and initial empty chart |
| `ui.py` | Plotly globe and historical chart figures |
| `callbacks.py` | Country selection and clear-selection behaviour |
| `assets/style.css` | Typography, panel layout, spacing and responsive styles |
| `requirements.txt` | Dashboard dependencies |
| `tests/` | Data, figure and callback tests |
| `Dockerfile` | Existing placeholder; must be replaced before deployment |
| `eda/` | Exploratory notebook |

Dash loads the CSS from the `assets` directory automatically.

## Run locally

Use Python 3.13 to match the repository's CI configuration.

From the repository root:

```powershell
python -m pip install -r requirements-dev.txt -r dash_app/requirements.txt
```

Both files are currently needed: the dashboard requirements do not declare
Boto3 directly, and the development requirements do not include all
dashboard dependencies.

Authenticate with AWS using your usual local credentials or profile.
If using a named profile in PowerShell:

```powershell
$env:AWS_PROFILE = "your-profile-name"
```

Start the app:

```powershell
python -m dash_app.app
```

Open http://127.0.0.1:8050.

The app currently runs with `debug=True` for local development. After CSS
changes, refresh the browser with Ctrl+F5 if necessary.

## Current configuration

These values are defined in `app.py`:

| Setting | Value |
| --- | --- |
| AWS region | `eu-north-1` |
| S3 bucket | `webgis-population-app` |
| S3 key | `data/enriched_population_data.json` |

The AWS identity running the backend needs `s3:GetObject` permission for
the dataset object.

The browser does not need AWS credentials. Do not embed credentials in
source code or Docker images.

Startup requires a readable dataset and at least one year meeting the
map-coverage threshold. S3 read failures or insufficient coverage stop
application startup.

## Tests

From the repository root:

```powershell
python -m pytest -q
```

To run only dashboard tests:

```powershell
python -m pytest dash_app/tests -q
```

The tests cover:

- Successful and failed S3 reads.
- Year conversion and invalid-year handling.
- Economy filtering and chronological ordering.
- Globe codes and logarithmic population values.
- Historical chart generation.
- Selecting, clearing and reselecting an economy.
- Missing or unknown selections.
- Preservation of the Viridis scale.
- Presence of the initial chart container.

These tests exercise Python logic and callback responses. They do not
verify real browser dragging, clicking or responsive rendering.

Before merging interface changes, check:

1. The globe displays and rotates.
2. Selecting an economy fills the details panel.
3. Clear selection restores the empty panel.
4. The same economy can be selected again.
5. The history chart remains inside its panel.
6. The map note and footer do not overlap.
7. Resizing the browser does not unexpectedly shrink the globe.

## AWS deployment: planned

The dashboard will be deployed through GitHub Actions, separately from
the ingestion Lambda.

The intended workflow is:

1. Run CI with both ingestion and dashboard dependencies.
2. Authenticate with AWS using GitHub OIDC.
3. Build the dashboard container on the GitHub Actions runner.
4. Push the image to a dashboard ECR repository.
5. Deploy the image to a separate dashboard Lambda.
6. Verify the application through its HTTPS endpoint.

The planned container runs Gunicorn with AWS Lambda Web Adapter.
Docker Desktop is not required for this workflow.

### Remaining implementation

- Replace the current Dockerfile, which still references
  `lambda_function.py` and `lambda_handler`.
- Expose the Flask server with `server = app.server`, or add an equivalent
  production entry point.
- Declare the production runtime dependencies, including Gunicorn and Boto3.
- Implement `.github/workflows/deploy_dashapp.yml`, which is currently empty.
- Configure the dashboard ECR repository, Lambda execution role, function
  and HTTPS endpoint.
- Grant the dashboard execution role read access to the S3 dataset.
- Configure the GitHub deployment role and repository variables.
- Verify a successful deployment before documenting a live URL.

The GitHub deployment role controls deployment actions. The Lambda
execution role controls what the running dashboard can access.

## Known limitations

- No automatic dataset refresh while the application process is running.
- AWS configuration is currently defined in Python rather than environment
  variables.
- No multi-economy comparison or map-year selector.
- No broader data-quality validation suite.
- Graph sizing and responsive behaviour require manual browser verification.
- No verified public dashboard deployment yet.