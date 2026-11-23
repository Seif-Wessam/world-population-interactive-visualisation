# Engineering Decisions — World Bank Agentic Analytics

**Purpose:** Explain *why* the agentic extension is structured as it is, distinguish implemented choices from architectural intentions, and record the trade-offs that matter for correctness, reproducibility, security and cost.

**Reviewed against repository code:** November 2026. The current integration lives in `agentic_framework/main.py`; `controller.py`, `cache.py`, `audit.py` and `config.py` are empty placeholders. “Accepted” below indicates a design decision, **not** necessarily a fully implemented system.

## ADR-001 — Raw-first ELT-style source preservation

**Status:** Partially implemented (raw JSON and normalized Parquet writes); cache management pending.  
**Context:** World Bank sources have different schemas, meanings, revisions and units. The original responses should remain inspectable when normalization changes.  
**Decision:** Persist source observations and metadata before normalization; derive separate analytical tables; use DuckDB for subsequent SQL computation.  
**Implementation:** `main.py` currently writes `raw.json`, `metadata.json`, `observations.parquet` and `indicators.parquet` to S3 when `AGENT_SKIP_S3` is not set.  
**Alternatives:** Transform-first ETL without raw retention; query MCP live on every analysis with no persistence.  
**Trade-offs:** More storage and data-management work. Keys are deterministic and can be overwritten; no immutable snapshot ID, read-back cache, freshness policy or retention governance yet.  
**Revisit when:** Versioned storage, reproducible reruns or multi-user concurrency becomes necessary.

## ADR-002 — Keep source discovery grounded in MCP responses

**Status:** Implemented for supported indicator discovery.  
**Context:** A model can invent plausible-looking indicator identifiers.  
**Decision:** Qwen may request the Data360 indicator-search tool, but Python records actual `(database_id, indicator_id)` pairs and rejects a final selection that was not returned by MCP.  
**Implementation:** `discover_indicator()` in `main.py` supports repeated search attempts with a bounded turn count. `mcp_client.py` allowlists Data360 tools.  
**Alternatives:** Hard-code all indicators; allow free-form model IDs.  
**Trade-offs:** Extra latency and model/tool calls; search results may still be semantically ambiguous. Catalog presence does not prove the selected indicator is appropriate to the user's question.  
**Revisit when:** Adding interactive clarification, ranking, or cached catalog metadata.

## ADR-003 — Use a hosted, open-weight model through an API

**Status:** Implemented as an integration; dependent on service availability.  
**Context:** A development machine need not run a dedicated GPU or host inference on AWS.  
**Decision:** Use Qwen via Hugging Face `InferenceClient`; current `llm_client.py` configures the `deepinfra` provider and reads credentials from `HF_TOKEN`.  
**Alternatives:** Self-host a model, use a different managed provider, or remove model assistance.  
**Trade-offs:** Network dependency, provider billing, rate limits, model version behavior and possible provider-specific request handling. The client is not yet fully provider-agnostic.  
**Revisit when:** Reproducibility, inference costs, latency or data-governance requirements justify another host/model.

## ADR-004 — Separate model interpretation from numerical computation

**Status:** Implemented in the prototype.  
**Context:** Generative models may hallucinate arithmetic or infer values not in source data.  
**Decision:** Let Qwen choose an indicator and propose SQL, but let Python fetch, normalize, validate and execute; numerical results are calculated by DuckDB.  
**Implementation:** `answer_question()` constructs approved tables, inspects their live schema, asks for SQL, and passes that query through `analytics.py` and `sql_guard.py`.  
**Alternatives:** Ask the LLM to reason directly over raw observation text; build a rigid hard-coded query interface.  
**Trade-offs:** Still vulnerable to **semantically wrong but valid SQL**, incorrect indicator selection and mismatched units. Independent reference-query evaluation remains essential.  
**Revisit when:** Adding complex comparisons, joins or user-facing explanations.

## ADR-005 — Use DuckDB and schema-restricted SQL, not unrestricted database access

**Status:** Implemented for the current SQL subset.  
**Context:** Model-generated queries must not alter source data, access arbitrary files or invoke dangerous SQL features.  
**Decision:** Copy trusted normalized DataFrames into an in-memory DuckDB connection; disable external access; validate one supported `SELECT` statement against approved tables and columns with SQLGlot.  
**Alternatives:** Execute arbitrary SQL; use a full persistent PostgreSQL server; replace SQL generation with fixed Python functions.  
**Trade-offs:** The intentionally restrictive guard disallows CTEs, nested queries, window functions and `SELECT *`, limiting analytic expressiveness. Parsing and allowlisting are **not a complete security sandbox**.  
**Revisit when:** Expanding query complexity, managing concurrent users, or introducing deployment isolation and stricter resource governance.

## ADR-006 — Bound pagination and reject unsupported analytical shapes

**Status:** Implemented for the current one-indicator/one-country annual scope.  
**Context:** MCP tools may paginate, data may be incomplete, and source dimensions or units may not match assumptions.  
**Decision:** Follow `has_more`/`next_offset` with a page cap; reject invalid pagination and unsupported disaggregations, frequencies, unit multipliers or duplicate observations during normalization.  
**Alternatives:** Truncate to the first page; silently coerce unsupported shapes.  
**Trade-offs:** Reliable rejection is preferable to wrong answers, but legitimate nonannual or disaggregated datasets cannot yet be used. Pagination completion alone does not guarantee a consistent source snapshot.  
**Revisit when:** Supporting multidimensional datasets, unit conversions, or multi-indicator joins.

## ADR-007 — Keep indicator metadata separate from observations

**Status:** Implemented as two normalized tables.  
**Context:** Indicator definitions and units are not the same kind of data as country-year measurements.  
**Decision:** Normalize observations and indicator metadata separately, and expose them as approved DuckDB tables.  
**Implementation:** `normalize_observations()` creates `indicator_id`, `country_iso3`, `year`, and `value`; `normalize_metadata()` prepares indicator details including database, name, unit, definition and periodicity.  
**Alternatives:** Duplicate metadata on every observation; use a single unstructured raw response.  
**Trade-offs:** Some queries need a join and explicit compatibility checks. Current normalization intentionally drops some source-level dimensions from the curated table; full provenance requires preserving the raw payload and richer identifiers.  
**Revisit when:** Source schemas add dimensions or unit-specific observation metadata that must be reflected in queries.

## ADR-008 — Evaluate source retrieval separately from text-to-SQL correctness

**Status:** Initial evaluation scripts exist; no fixed published accuracy claim.  
**Context:** A valid SQL query can still produce a wrong answer; WDI S3 population and live Data360 data can differ in definition, revision or coverage.  
**Decision:** Test the SQL transformation layer against known/reference queries and separately examine MCP retrieval and cross-source comparisons.  
**Implementation:** `evaluation/text_to_sql_benchmark.py`, `evaluation/live_mcp_vs_s3.py`, and other experimental scripts; unit and integration test modules.  
**Alternatives:** Check only that queries execute, or assume existing S3 values are universal ground truth.  
**Trade-offs:** Reference cases require curated source snapshots, documented semantics and controlled model/provider versions. Any live results are observations, not guarantees.  
**Revisit when:** Producing versioned benchmark reports and confidence statistics.

## ADR-009 — Separate the deployed dashboard from the experimental agent

**Status:** Local agent UI implemented; deployed dashboard remains agent-free.  
**Context:** The population dashboard is deployed, while the agent relies on paid inference, live MCP calls and model-generated SQL.  
**Decision:** Integrate the experimental agent into a locally run Dash tab, while keeping agent inference out of the public Lambda deployment until correctness, security, cost and operational monitoring mature.  
**Alternatives:** Expose the agent directly in the public dashboard now.  
**Trade-offs:** Users cannot yet query arbitrary indicators through the deployed UI, but the deployed application remains simpler and its cost exposure more predictable.  
**Revisit when:** End-to-end tests, rate limits, authentication, audit logs and model-cost controls are in place.

## ADR-010 — Plan explicit snapshot caching and auditable execution (not yet implemented)

**Status:** Proposed.  
**Context:** Repeated MCP queries cost time and can return revised data; a useful analytical result should identify the inputs and SQL behind it.  
**Proposed decision:** Add immutable S3 snapshot IDs, content hashes, retrieval timestamps, source metadata, cache-hit/freshness rules and per-analysis provenance records. Implement this through dedicated `cache.py`, `audit.py` and orchestration modules.  
**Current reality:** The files exist but are empty. `main.py` persists raw and curated objects under predictable keys and returns SQL/metadata to the caller, but has no reusable cache catalog or durable audit record per question.  
**Trade-offs:** More orchestration, storage and schema migration complexity; cache invalidation and source-revision semantics must be explicit.  
**Revisit when:** The workflow is stable enough to establish a durable, testable cache contract.

---

## ADR-011 — Combine independently normalized indicators in a shared analytical table

**Status:** Implemented and live-tested for a two-indicator annual comparison (November 2026).  
**Context:** Extending the agent from one to multiple World Bank indicators raised a choice between dynamically creating a table per indicator, implementing broader SQL join support immediately, and retaining one stable schema. Existing `sql_guard.py` deliberately restricts self-joins, CTEs, subqueries and window functions.  
**Decision:** Decompose a question into measurement requirements and discover each indicator separately. Independently retrieve, normalize and validate the observations for each selection. Concatenate the normalized observations into one long-form DuckDB `observations` table (`indicator_id`, `country_iso3`, `year`, `value`), with a separate `indicators` metadata table. For compatible annual comparisons, allow Qwen to propose conditional aggregation, e.g. `MAX(CASE WHEN indicator_id = ... THEN value END)` grouped by year (and country when appropriate), while retaining the existing SQL guard.  
**Why:** Preserves a stable analytical schema and per-indicator provenance without broadening the guard prematurely. Source datasets remain independent during retrieval, normalization and optional S3 persistence; the combined table is a query-time representation. Duplicate indicator/country/year observations are rejected so conditional aggregation extracts one value rather than silently choosing among duplicates.  
**Alternatives:** Dynamic indicator-specific tables requiring broader joins; raw joins between observation rows; hard-coded pivoting in Python.  
**Trade-offs:** Supports elementary aligned annual series, not general relational analytics. Conditional aggregation must group on all relevant dimensions; different units remain distinct and are not automatically converted. The current guard intentionally limits advanced queries, and neither valid provenance nor a selected year range guarantees semantic suitability or complete annual coverage.  
**Validation:** An opt-in live test retrieved Egypt's total population and life expectancy from 2000 through 2023 and compared 24 result rows with independently retrieved World Bank MCP observations. This is one validated two-indicator case, not evidence of arbitrary N-indicator reliability.  
**Revisit when:** Adding controlled joins, window functions, CTEs, multi-country analysis, broader dimensions or additional query shapes, always with independent correctness and SQL safety tests.

## ADR-012 — Local Dash agent GUI before protected deployment

**Status:** Implemented locally; not deployed.  
**Context:** The existing population dashboard is AWS-hosted, while the agent is experimental and can require multiple paid Qwen requests and long MCP retrievals.  
**Decision:** Add a separate AI Data Analyst tab in Dash with question submission, table, SQL and indicator metadata, using a thin callback adapter to `answer_question()`. Keep live inference opt-in (`AGENT_UI_LIVE=1`) and require `AGENT_SKIP_S3=1` in this local UI. Test the Dash callback offline by substituting a fake backend.  
**Trade-offs:** The synchronous `asyncio.run()` adapter is only for local development; it is not a suitable unrestricted public Lambda request handler. The interface currently returns data, not a grounded natural-language analytical answer.  
**Revisit when:** Implementing grounded answer synthesis, bounded background job execution, server-side authentication, rate and cost limits, and an access-controlled deployment.

## ADR-013 — Bounded follow-up SQL and evidence-grounded answer synthesis

**Status:** Accepted on 19 November 2026; implemented locally.  
**Context:** The current workflow returns validated SQL results but no natural-language answer. A fixed catalog of follow-up calculations would restrict the analytical questions the project can answer.  
**Decision:** After the initial successful query, let Qwen request further queries through a single `run_sql(query)` tool against the same open DuckDB connection, or propose a final answer. Every query must pass the existing SQL guard and execute through the analytical layer. This first loop does not perform additional MCP discovery or retrieval, and does not broaden the supported SQL subset. Qwen chooses calculations; DuckDB performs them.  
**Evidence:** Maintain a per-question registry of successful SQL and result DataFrames, beginning with `result_0` for the initial result. Assign subsequent IDs only to successful executions. Preserve initial evidence independently of later failures. This is an in-memory execution record, not the durable snapshot/audit system proposed in ADR-010.  
**Retries and termination:** Return actionable SQL validation/execution errors to Qwen for correction. Every follow-up attempt, including rejected queries, consumes a bounded attempt budget. Bound model turns and evidence size as well; do not silently truncate a result and present it as complete. Exact limits and oversized-result handling remain implementation decisions. At the limit, disable further tools and permit one final synthesis call using successful evidence. If synthesis fails or cannot be validated, Python returns the initial result and a fixed explanation of the incomplete analysis. The initial result may be a series or an aggregate; an initial-query failure is outside this fallback guarantee.  
**Numerical grounding:** Qwen proposes an answer template and structured references to cells in registered results. Python validates references and renders numerical values using controlled formatting. Unsupported numerical claims must not bypass the reference mechanism through free text; validation and bounded correction are required. Failed calculations do not authorize model arithmetic. Derived numerical claims require successful computed evidence. Preserve missing values and units; do not silently substitute available endpoint years for requested years.  
**Interpretation boundary:** Qwen retains responsibility for wording and interpretation, including increase/decrease language. Valid cell references establish numerical provenance, not correct interpretation, appropriate indicator selection or semantically correct SQL. Evaluate these separately. Deterministic calculations on fixed inputs do not imply deterministic model query choices or prose.  
**Alternatives:** A fixed calculation catalog before synthesis; unrestricted model arithmetic; unbounded tool use; discarding the initial result when a follow-up fails.  
**Trade-offs:** Greater analytical flexibility within the existing guard, at the cost of more latency, inference calls and control-flow complexity. Referenced numbers can still be described incorrectly. Retained evidence and explicit partial outcomes provide useful results without claiming full analytical success.  
**Validation planned:** Offline mocked-model tests for successful follow-ups, rejected SQL followed by recovery, exhausted budgets, invalid references, failed final synthesis and preservation of the original result. Numerical tests for increasing/decreasing series, chronological endpoint change rather than extrema, missing endpoints and zero denominators. Test evidence limits and semantic claims separately; measure latency and usage in controlled live runs.  
**Revisit when:** Adding retrieval tools, broader SQL capabilities, persistent evidence, stronger semantic validation or protected asynchronous deployment.

## ADR-014 — Incremental controller extraction and partial outcomes

**Status:** Accepted on 19 November 2026; implemented locally.  
**Context:** Follow-up analysis introduces conversation state, evidence, tool dispatch and budgets. The existing Dash adapter relies on the return contract of `answer_question()`.  
**Decision:** Populate the existing `controller.py` incrementally, initially with the analytical loop invoked after the first successful query. Keep `answer_question()` and connection ownership in `main.py` during this step. The controller borrows the open connection and does not close it. The owner closes it in `finally` on normal return or propagated exceptions. Budget exhaustion ends tool use; final synthesis or fallback is completed before the workflow returns. Moving the entire orchestrator into the controller is a later refactor, not required to introduce the loop.  
**Return contract:** Preserve the original `results` DataFrame and its matching `sql`, plus existing metadata and other fields. Add `answer`, `analysis_status` and `analysis_reason` for explicit complete/partial outcomes. Keep follow-up SQL/result pairs in the evidence registry rather than overwriting the initial pair. Expected budget exhaustion returns a partial outcome; unexpected failures require explicit handling rather than being indiscriminately treated as successful analysis. Status is machine-readable workflow information, not a guarantee of semantic correctness.  
**UI consequence:** Existing callbacks can continue displaying the initial table, SQL and metadata. Displaying the answer and partial status requires an explicit GUI change. Pushing code makes it available to clones after a pull; it neither updates existing clones automatically nor deploys the agent publicly.  
**Implementation sequence:** First implement a per-question evidence registry, then the bounded controller and validated synthesis, then UI rendering. Preserve evidence against accidental caller mutation; reject ambiguous duplicate result column labels before cell referencing. Each stage receives offline tests and a design review before the next stage.  
**Alternatives:** Move the entire workflow at once; let the controller close a borrowed connection; discard initial results on exhausted follow-ups; infer status by parsing model prose.  
**Trade-offs:** A temporary split between initial orchestration and follow-up control reduces simultaneous changes and preserves compatibility. The new contract needs tests even while the GUI ignores its added fields.  
**Validation planned:** Registry isolation and unambiguous references; partial-result preservation; SQL/result pairing; connection cleanup on normal and exceptional exits; existing callback compatibility.  
**Revisit when:** The loop is stable enough to move full orchestration out of `main.py`.

## ADR-015 — Direct answer synthesis from executed SQL evidence

**Status:** Implemented locally; live-tested on 23 November 2026.
Supersedes the numerical template/reference mechanism in ADR-013.

**Context:** Requiring answer templates with cell references introduced
formatting failures and additional complexity. Valid references still
did not guarantee correct interpretation: a population cell could be
incorrectly described as a year.

**Decision:** Let Qwen return a natural-language answer directly from
the supplied SQL results and metadata. Remove placeholder rendering
and validate that the answer is non-empty text. Retain the evidence
registry, guarded SQL execution, bounded follow-up queries, evidence
size limits, and preservation of the first successful SQL/result pair.
The controller executes the initial query and any follow-ups; main
owns the connection and closes it in finally.

**Grounding:** Instruct Qwen to obtain calculations through SQL,
accurately reproduce results, preserve units, acknowledge missing
data, and limit conclusions to what the evidence supports. Endpoint
comparisons must select observations by year rather than substitute
minimum and maximum values across the period.

**Trade-offs:** Simpler synthesis and fewer formatting failures.
Numerical accuracy and completeness of the prose are not enforced
deterministically. Prompt instructions and live evaluations improve
confidence but do not guarantee future correctness. A complete status
means the workflow accepted an answer, not that its semantics were proven.

**Alternatives:** Retain placeholder-based rendering; use fixed answer
templates; introduce richer semantic validation.

**Validation:** A live Egypt population comparison for 2000 and 2023
produced explicit endpoint SQL and an answer matching its returned
populations, absolute change, and percentage change. Offline controller
tests were updated for string answers and invalid-answer recovery.
This live case does not establish general analytical accuracy.

**UI consequence:** Displaying the answer and status requires explicit
GUI changes. Supporting follow-up results should also be exposed when
the answer relies on them.

**Revisit when:** Broader evaluations reveal recurring numerical or
interpretation errors, or stronger guarantees become necessary.

## Decision review checklist

When a decision changes, record: **context → decision → alternatives → implementation status → consequences → tests → conditions for revision**. Avoid labeling a proposed future architecture as deployed or production-ready. Update this log alongside significant changes to `main.py`, retrieval/normalization behavior, SQL restrictions and storage semantics.
