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

**Status:** Current repository boundary.  
**Context:** The population dashboard is deployed, while the agent relies on paid inference, live MCP calls and model-generated SQL.  
**Decision:** Keep agent experimentation local and separate from the public Lambda dashboard until correctness, security, cost and operational monitoring mature.  
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

## Decision review checklist

When a decision changes, record: **context → decision → alternatives → implementation status → consequences → tests → conditions for revision**. Avoid labeling a proposed future architecture as deployed or production-ready. Update this log alongside significant changes to `main.py`, retrieval/normalization behavior, SQL restrictions and storage semantics.
