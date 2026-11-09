# Architecture Decision Log

**Project:** World Population Explorer — Agentic Analytics Extension

**Purpose:** Record important architectural decisions, the reasons behind them, alternatives considered, trade-offs and conditions for revisiting each decision.

---

## ADR-001 — Adopt a raw-first ELT-style data pipeline

**Date:** 2026-11-08  
**Status:** Accepted — implementation pending  
**Component:** Data ingestion and storage

### Context

The agent will dynamically retrieve World Bank indicators through the Data360 MCP server. Different datasets may have different units, definitions, geographical coverage, time periods and disaggregation dimensions.

We need a data pipeline that supports reproducible analytics, caching, new indicators and independent verification of numerical results.

### Decision

Adopt a raw-first, ELT-style architecture:

1. **Extract:** Retrieve observations and metadata through World Bank Data360 MCP.
2. **Load raw:** Store the original response and retrieval metadata in Amazon S3.
3. **Transform:** Normalize supported observations into a consistent analytical schema and write Parquet files.
4. **Analyze:** Expose approved Parquet datasets to DuckDB for SQL queries.

This is a hybrid ELT/ETL design because normalized data is prepared before DuckDB queries it.

### Alternatives considered

**Traditional ETL:** Transform observations before storing them.

- Simpler when data structures are fixed.
- Less suitable for preserving complete source responses and revisiting previous transformations unless a separate raw archive is maintained.

**Direct MCP queries without persistent caching:**

- Simpler initial implementation.
- Requires repeated API requests and complicates reproducibility and comparison across data revisions.

### Rationale

- Preserve original World Bank observations and metadata.
- Allow transformations to be corrected without unnecessarily retrieving source data again.
- Support independent auditing of analytical results.
- Reduce repeated MCP requests through caching.
- Support a standardized analytical schema across different indicators.
- Use Parquet for efficient analytical queries through DuckDB.

### Consequences and trade-offs

- S3 will contain both raw and processed data, increasing storage requirements.
- Cache completeness, freshness, and source versions must be tracked.
- Transformation code must preserve units and relevant dimensions.
- Raw data retention alone does not guarantee numerical correctness.
- Additional orchestration logic is required.

### Revisit this decision if

- Storage or operational costs become excessive.
- Source data volume or complexity requires a different architecture.
- The application requires near-real-time data rather than periodically refreshed analytical datasets.

---

## ADR-007 — Separate indicator metadata from observations
- Decision: Store indicator definitions, units and source information separately from numerical observations.
- Rationale: Avoid repeated metadata, provide Qwen with reliable indicator descriptions, and support a standardized analytical schema.
- Trade-off: Some queries require joining observations with metadata.
- Important exception: Preserve observation-level units and multipliers when the source data requires them.

---

## Template for future decisions

### ADR-XXX — Decision title

**Date:**  
**Status:** Proposed / Accepted / Superseded  
**Component:**

**Context:** What problem are we solving?

**Decision:** What approach did we choose?

**Alternatives:** What other approaches did we consider?

**Rationale:** Why is this the preferred approach?

**Trade-offs:** What costs, limitations or risks does it introduce?

**Revisit if:** Under what circumstances should we reconsider it?
