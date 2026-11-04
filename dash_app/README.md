# Population dashboard

Dash and Plotly application reading the enriched historical dataset from S3.
It displays a globe, opens the selected economy's history and lets users clear
that selection. It has a responsive layout and excludes aggregate groups.

## Local development

From the repository root, install `requirements-dev.txt`, authenticate with AWS,
and run `python -m dash_app.app`. Open http://127.0.0.1:8050.
Tests run without AWS credentials: `python -m pytest -q`.

| Environment variable | Default |
| --- | --- |
| `POPULATION_BUCKET` | `webgis-population-app` |
| `POPULATION_KEY` | `data/enriched_population_data.json` |
| `AWS_REGION` | `eu-north-1` |

The app reads S3 at worker startup. Missing credentials, unreadable data or
insufficient map coverage stop startup rather than silently showing demo data.
A successful `/healthz` response means the worker loaded its initial data; it does
not continuously recheck S3 or guarantee that the dataset is fresh.

## Container

Build from the **repository root** (the Dockerfile expects that build context):

```sh
docker build --platform linux/amd64 -f dash_app/Dockerfile -t population-dashboard .
```

The image runs Gunicorn on port 8080. On Linux/macOS, one way to test with an
existing AWS credentials file is:

```sh
docker run --rm -p 127.0.0.1:8080:8080 \
  -e AWS_REGION=eu-north-1 -e AWS_PROFILE \
  -e AWS_SHARED_CREDENTIALS_FILE=/aws/credentials \
  -e AWS_CONFIG_FILE=/aws/config \
  -v "$HOME/.aws:/aws:ro" population-dashboard
```

This example assumes file-based credentials; SSO or `aws login` sessions may need
additional credential-provider setup inside the container. Open http://127.0.0.1:8080.
In Lambda, the execution role supplies credentials automatically.

## AWS deployment

**Status: deployment configuration prepared; live deployment not yet verified.**
The separate dashboard Lambda uses AWS Lambda Web Adapter to serve HTTP through a
public HTTPS function URL. The S3 bucket stays private. Anyone with the dashboard
URL can view the population data served by the app. AWS usage is billable.

### One-time AWS / GitHub setup

1. Ensure the ingestion dataset exists at the configured S3 key.
2. Create a dedicated GitHub OIDC deployment role for this repository's `main`
   branch. Reuse the account's GitHub OIDC provider if it already exists.
3. Set GitHub repository variable `AWS_DASH_DEPLOY_ROLE_ARN` to that role ARN.
   Optional variables: `POPULATION_BUCKET` and `POPULATION_KEY`.
4. The deployment role needs ECR build/push access for `population-dashboard`,
   CloudFormation deployment access for stack `population-dashboard-dev`, and
   permissions to create/update the stack's Lambda, URL/resource policies, log
   group and execution role. It also needs `iam:PassRole` for that execution role
   (restricted to `lambda.amazonaws.com`). See the resource template for the
   exact resources. The ingestion deployment role's permissions may not cover these.
5. ECR must allow Lambda to retrieve the image. The deployment identity needs
   `ecr:GetRepositoryPolicy` and `ecr:SetRepositoryPolicy` so Lambda can configure
   the repository policy when required.

Example **trust policy** for the dedicated deployment role (replace ACCOUNT_ID):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "arn:aws:iam::ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:Seif-Wessam/world-population-interactive-visualisation:ref:refs/heads/main"
      }
    }
  }]
}
```

The trust policy controls **who can assume the deployment role**. Its permission
policies control **what deployment can change**. The separately created dashboard
execution role trusts Lambda and can read only the configured S3 object and write
its logs. If that object uses a customer-managed KMS key, grant the execution role
`kms:Decrypt` on that key and allow it in the key policy as well.

### Deploy and verify

1. Push changes to `main`.
2. Open **Actions → Deploy dashboard to AWS → Run workflow** on `main`.
3. The workflow runs tests and a container build, authenticates with OIDC, creates
   an ECR repository if missing, uploads a unique image tag and deploys the stack.
4. It checks `/healthz` and `/_dash-layout`. The public URL appears in the run summary.
5. Open the URL, rotate the globe, click an economy and clear the history. Check on
   a narrow screen too. Add the verified live URL to the main README.

For later versions, push and run the same workflow. The new image URI updates the
same function. This is manual continuous delivery; it does not deploy on each push.
The image tag identifies the GitHub Actions run and attempt. For rollback, redeploy
`infra/dashboard.yml` with a previously successful `ImageUri` and the same parameters.

## Operations and limits

- Logs: `/aws/lambda/population-dashboard-dev`, retained for 14 days.
- Settings: 1024 MB memory, 60-second timeout, x86_64, one Gunicorn worker.
- Data is cached per worker; redeploy after ingestion if an immediate refresh is needed.
- The public endpoint has no login; do not point it at a private or sensitive dataset.
- S3 permission errors prevent worker startup. Check the execution role and object key.
- A 403 at the function URL can mean one of its two public invocation permissions
  is missing. Both are included in the template.
- Stop hosting by deleting the dashboard CloudFormation stack. This removes its
  function, URL, role and logs; it leaves the dataset, ingestion and ECR repository.
  Remove unused dashboard ECR images separately when no longer needed for rollback.

References: [Lambda Web Adapter](https://github.com/aws/aws-lambda-web-adapter),
[function URL permissions](https://docs.aws.amazon.com/lambda/latest/dg/urls-auth.html).
