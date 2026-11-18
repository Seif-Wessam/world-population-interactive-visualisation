# World Bank Agentic Analytics Framework

**An experimental Python pipeline for traceable, LLM-assisted analysis of World Bank development indicators.**

**Current status (November 2026): locally validated research prototype, not a production service.** The code implements hosted Qwen inference, multi-indicator MCP discovery, paginated retrieval, normalization, guarded DuckDB SQL, optional S3 persistence, and evaluation scripts. A local Dash AI Data Analyst tab invokes this backend; the publicly deployed [World Population Explorer dashboard](../README.md) does **not** expose the agent.

The central design choice is to **let the model interpret and propose, while Python validates and executes**. Numerical answers come from DuckDB queries on retrieved source data, not from an LLM inventing figures.

## 1. What works today

| Stage | Implementation | Status |
| --- | --- | --- |
| Hosted model | `llm_client.py` uses Hugging Face `InferenceClient`, configured with the DeepInfra provider and a Qwen model | Implemented; requires provider credentials |
| Indicator discovery | `discovery.py` decomposes questions and discovers each indicator through Data360 MCP; returned IDs and scope are validated | Implemented; multi-indicator path live-tested |
| Source retrieval | `mcp_client.py` allowlists Data360 tools and paginates observation retrieval; `main.py` retrieves metadata separately for each selection | Implemented for selected annual datasets |
| Normalization | `transform.py` validates annual data, units, identifiers, disaggregation assumptions and duplicates | Implemented for supported schemas |
| SQL generation | `main.py` prompts the model with the live DuckDB schema and selection | Implemented |
| SQL restrictions | `sql_guard.py` parses SQL with SQLGlot; `analytics.py` limits the schema and executes in in-memory DuckDB | Implemented with restricted SQL subset |
| Persistence | `main.py` optionally writes raw response/metadata JSON and normalized Parquet to S3 | Implemented as writes, **not cache reads** |
| Tests / evaluation | Unit and integration tests plus reference-SQL, MCP-versus-S3 and text-to-SQL evaluation scripts | Implemented as scripts/tests; results vary with live services |
| Durable cache catalog and freshness policy | Empty `cache.py` placeholder | **Not implemented** |
| Reusable controller/config/audit modules | `controller.py`, `config.py`, `audit.py` currently empty | **Not implemented** |
| Local Dash GUI | `dash_app/agent/` calls the framework and displays a results table, SQL and metadata | Implemented locally; offline GUI tests |
| Grounded narrative answer, protected public API/deployment | Planned | **Not implemented** |

Do not equate an existing module or test file with a production-ready implementation. In particular, live correctness and inference reliability are still being evaluated.

## 2. Current supported workflow

 ```mermaid
flowchart TD
    U[Question] --> Q[Qwen: decompose measurements]
    Q --> D[Discover and validate each indicator via Data360 MCP]
    D --> R[Fetch pages and metadata independently]
    R --> T[Normalize and validate each dataset]
    R -.-> P[(Optional S3 raw and Parquet writes)]
    T -.-> P
    T --> C[Concatenate long-form observations and indicators metadata]
    C --> B[(In-memory DuckDB)]
    B --> SC[Inspect allowed schema]
    SC --> G[Qwen: generate SQL]
    G --> V[SQLGlot guard]
    V --> E[DuckDB execution]
    E --> O[Result DataFrame, SQL, metadata and selections]
    O --> UI[Local Dash results UI]
```

`answer_question(question)` in `main.py` is the orchestration entry point. It:

1. Uses Qwen to decompose a question into measurement requirements and iteratively discover each indicator. Final indicator/database identifiers must originate from observed MCP search results, and selected scope is checked.
2. Retrieves each selected indicator's paginated observations and metadata independently.
3. Optionally persists each raw payload and normalized Parquet dataset to S3 before/after transformation.
4. Normalizes and validates per-indicator annual observations, then combines them into a shared long-form `observations` table and a separate `indicators` metadata table.
5. Asks Qwen for SQL over the actual DuckDB schema. For basic multi-indicator series, conditional aggregation can align indicators without self-joining observations.
6. Uses `sql_guard.py` to validate the generated SQL, executes it in DuckDB, and returns a DataFrame, SQL, selections and metadata.

**Scope:** One or multiple indicators for compatible annual observations; the tested multi-indicator case covers two indicators and one country. CTEs, subqueries, windows and observation self-joins remain unsupported. Selected date ranges are not proof of complete annual coverage. Valid SQL does not establish semantic correctness. **The model does not yet synthesize a natural-language answer from the SQL result.** The SQL guard is defense in depth, not a full security sandbox.

## 3. Design choices

- **World Bank Data360 MCP instead of invented indicator identifiers:** the model must search the live tool and select an observed indicator/database pair.
- **Bounded tool access:** Python exposes specific MCP tools, not unrestricted model execution; the discovery loop has a fixed turn limit and observation pagination has a page cap.
- **Raw-first persistence:** retain source payloads so transformations can later be audited. Current S3 keys under `agent_cache/prototype/` are predictable and can be overwritten by another run with the same selection; immutable versioning is **not** in place.
- **DuckDB over an always-on database server:** suitable for local analytical computation over limited data volumes.
- **SQLGlot validation + restricted DuckDB connection:** validates table/column usage and supported SQL constructs and disables external access in the DuckDB connection.
- **Shared long-form multi-indicator table:** normalize independently, then concatenate observations and use conditional aggregation for basic annual comparisons; advanced join/window/CTE capabilities are deferred until the SQL guard is extended and tested.
- **Separate evaluations:** fixed-S3-population text-to-SQL benchmarks and live Data360 comparisons test different failure modes; their sources and versions are not interchangeable.

Detailed trade-offs and proposed follow-ups: [Architecture Decision Log](docs/DECISIONS.md).

## 4. Repository map

| Path | Purpose |
| --- | --- |
| `main.py` | Orchestration, independent retrieval, normalization, S3 writes, combined DuckDB analysis |
| `discovery.py` | Multi-requirement indicator search, selection validation and deduplication |
| `llm_client.py` | Hosted Qwen completion and tool-calling requests |
| `mcp_client.py` | Allowlisted MCP calls and pagination-aware observation retrieval |
| `transform.py` | Normalize and validate observations/metadata |
| `analytics.py` | Create in-memory DuckDB tables, inspect schema, execute guarded queries |
| `sql_guard.py` | Parse/restrict generated SQL using SQLGlot |
| `evaluation/` | Reference-query benchmarks, S3 comparisons, MCP/SQL experiments |
| `tests/` | Unit and integration tests; live tests may depend on external services |
| `docs/DECISIONS.md` | Engineering decisions and trade-offs |
| `cache.py`, `audit.py`, `controller.py`, `config.py` | Reserved empty modules; future refactoring targets |

## 5. Local setup

Use Python 3.13 and a virtual environment, from the repository root:

```powershell
python -m pip install -r agentic_framework/requirements.txt
```

Configure the model credentials in an ignored `agentic_framework/.env` (see `.env.example`) or your process environment. The current `llm_client.py` reads `HF_TOKEN`, uses `MODEL_NAME` (default `Qwen/Qwen3.5-9B`) and sets the inference provider to `deepinfra` in code. **Check your account's availability, pricing and quota.** Do not commit real credentials.

To test MCP connectivity only:

```powershell
python -m agentic_framework.mcp_client
```

To run the integrated prototype without writing to S3:

```powershell
$env:AGENT_SKIP_S3 = "1"
python -m agentic_framework.main
```

To enable prototype writes to S3, unset `AGENT_SKIP_S3` or set it to `0`; configure AWS credentials with appropriate `s3:PutObject` permissions and optionally `AGENT_S3_BUCKET` and `AWS_REGION`. **These writes may replace objects at matching deterministic keys.** Use a development bucket for experiments. The agent requires connectivity to the Data360 MCP endpoint and the model provider.

Run unit tests:

```powershell
python -m pytest agentic_framework/tests -q
```

Some integration tests and `evaluation/` scripts require live MCP/inference access and may incur usage costs. They are not prerequisites for a local-only unit test run.

## 6. Evaluation: what counts as a correct answer?

A SQL query being syntactically valid is not enough. Tests and experiments cover multiple layers:

1. **Selection and retrieval:** Did the model choose an actual Data360 indicator with the right meaning and units? Were all response pages retrieved and the intended country/year scope respected?
2. **Schema and SQL safety:** Was the query restricted to approved tables and supported read-only syntax?
3. **Numerical/semantic correctness:** Do results match independently specified reference calculations, including filters, missing values, sorting and aggregations?
4. **Source comparability:** Where S3 population observations are compared with live MCP results, do definitions, indicator IDs, coverage, revisions and dimensions align?

Available scripts include `evaluation/text_to_sql_benchmark.py`, `evaluation/live_mcp_vs_s3.py` and `evaluation/evaluate_multi_indicator.py`. A live two-indicator Egypt population/life-expectancy run for 2000–2023 passed a numerical comparison against independently retrieved MCP data (24 annual result rows). This is a single observed run, **not** a guaranteed accuracy level.

## 7. Limitations and safety boundaries

- Multi-indicator questions are supported for compatible annual series, but only basic two-indicator comparisons have been live-verified; advanced SQL and wider country/dimension scopes are not supported by the present guard. Unsupported disaggregations or unit multipliers are intentionally rejected.
- S3 persistence is **write-only in the current request path**; there is no lookup, freshness tracking, reuse or immutable snapshot catalog.
- Empty `controller.py`, `cache.py`, `audit.py` and `config.py` mean a generalized orchestration/audit architecture is not in place.
- Returned data is a structured Python result displayed by a **local experimental Dash UI**, not a deployed agent interface or a complete grounded prose answer with citations.
- SQLGlot checks do not replace runtime isolation, permissions, resource limits, semantic verification or security review.
- External inference and MCP availability, source revisions, token costs and errors can affect live experiments.
- The code is a research prototype and is **not suitable for an unrestricted public endpoint**.

## 8. Roadmap

- [x] Build MCP client, allowlist tools, and paginate supported observations.
- [x] Implement model-assisted indicator discovery tied to actual search results.
- [x] Normalize supported annual observations and metadata.
- [x] Implement in-memory DuckDB schema inspection, guarded SQL generation and execution.
- [x] Add optional raw JSON and normalized Parquet writes to S3.
- [x] Add initial unit/integration tests and evaluation scripts.
- [ ] Introduce immutable snapshot identifiers, cache catalog, and cache-hit/freshness behavior.
- [ ] Refactor the monolithic flow into reusable controller, config and audit modules.
- [ ] Add structured provenance records, reproducible evaluation outputs and stronger failure/cost limits.
- [x] Support independently discovered multiple indicators with a shared long-form analytical schema; live-verify a two-indicator annual comparison.
- [ ] Expand to additional countries, dimensions, complex joins and analytical SQL.
- [x] Integrate a development-only Dash tab (live inference opt-in; local tests).
- [ ] Add grounded answer synthesis, protected background execution, authentication, quotas and deployment.

## Sources and related documentation

- [World Population Explorer](../README.md) — independent deployed dashboard
- [Architecture Decision Log](docs/DECISIONS.md)
- [World Bank Data360 MCP](https://worldbank.github.io/data360-mcp/)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [DuckDB](https://duckdb.org/docs/) · [SQLGlot](https://github.com/tobymao/sqlglot)
