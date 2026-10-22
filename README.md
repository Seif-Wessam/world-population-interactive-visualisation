**world Population Interactive Visualisation**
An interactive data project for exploring how population changes across countries and over time, using World Bank data.

The project combines API ingestion, data transformation, and visualisation with a reproducible deployment workflow on AWS.
Status
Early development. A Python prototype has been tested in AWS Lambda: it retrieves the latest population observations and transforms the API response into simpler records.

The repository is being populated with the prototype. Historical analysis, aggregate classification, the interactive interface, Docker packaging, and CI/CD are planned.
What the project aims to answer
- How has a country's population changed over time?
- How do population levels and growth patterns compare between countries?
- How do regional and income-group aggregates differ from individual economies?
Data source
Population data comes from the World Bank Indicators API.
Resource	Purpose
Population, total — SP.POP.TOTL	Population observations by economy and year
Country API	Identifiers and classification metadata


The current prototype requests the most recent observation using mrv=1. Exploring change over time will require retrieving historical observations.

The API includes individual economies and aggregate groups. Aggregate classification will use the provider's metadata and identifiers rather than country-name matching.
Current prototype
The ingestion prototype:
1. Sends an HTTP request to the World Bank API.
2. Parses the JSON response into Python objects.
3. Selects the observation records from the response.
4. Produces a list of dictionaries containing country, date, and population.
5. Prints a small preview for inspection.
Missing population values are currently preserved as None in Python and null in JSON. The Lambda handler still returns a placeholder response.
Data quality and interpretation
Development will explicitly address:
- Pagination, so that requests do not silently omit records.
- Missing population observations and unmatched identifiers.
- Separation of individual economies from aggregates to avoid double counting.
- Years represented as strings in the source response.
- Preservation of source identifiers for reliable matching.
- Validation against source records and expected record counts.
Technology
Component	Status
Python, urllib.request, and json	Used in the prototype
AWS Lambda	Used to run the prototype
Git and GitHub	Repository established
Docker	Planned application packaging
Amazon ECR	Planned container image storage
GitHub Actions	Planned automated checks and deployment
Interactive visualisation framework	To be selected


The current Python prototype uses standard-library modules only.
Roadmap
- [ ] Add the working prototype and local development instructions.
- [ ] Add representative response samples and transformation checks.
- [ ] Enrich records with identifiers and an is_aggregate flag.
- [ ] Handle pagination and validate ingestion completeness.
- [ ] Retrieve historical population observations.
- [ ] Build an interactive interface for country and time comparisons.
- [ ] Build and test a Lambda-compatible Docker image locally.
- [ ] Automate checks, image publishing to ECR, and Lambda deployment.
- [ ] Document configuration, deployment, and operational checks.
Development workflow
Features will be developed locally on short-lived branches and reviewed before merging into main.

The planned deployment workflow will run checks, build a container image associated with a Git commit, publish it to ECR, and explicitly update Lambda to use that image. Automated deployment is not configured yet.
Documentation
- World Bank API request structure and parameters
- AWS Lambda Python container images
Data attribution and usage terms follow the World Bank indicator page.
