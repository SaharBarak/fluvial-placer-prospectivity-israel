# GoldFlow Israel

Agentic geospatial prospecting system that ranks **flowing** Israeli stream
segments by relative placer-gold potential — evidence-first, fully traceable,
guardrail-gated. Implements the MVP slice of `GoldFlow_Israel_PRD_Architecture.docx`.

The system never claims to detect gold from satellites and never marks a
target field-actionable without verified current flow, safety and legal review
(mineral prospecting in Israel requires a permit under the Mining Ordinance).

## Stack

FastAPI + Pydantic · PostgreSQL/PostGIS (EPSG:2039 canonical) · SQLAlchemy 2 +
GeoAlchemy2 · Alembic · Temporal (durable research workflow) · React +
TypeScript + MapLibre GL · uv · Ruff + Pyright strict + pytest + Hypothesis.

Architecture: Functional Core / Imperative Shell. Domain logic is pure, typed
and Result-monadic (`src/goldflow/domain`); I/O lives behind adapters
(`src/goldflow/infrastructure`); agents are deterministic policies over the
evidence store (`src/goldflow/agents`); orchestration is a Temporal workflow
(`src/goldflow/application/workflows`).

## Live data sources

| Source | Role | Authority |
|---|---|---|
| GSI ArcGIS (`egozi.gsi.gov.il`) — 1:200k geology + faults + vector tiles | lithology, structure, map overlay | Authoritative |
| Israel Water Authority via data.gov.il — springs catalog, measured spring discharge, hydrometric stations, streams registry | flow classification (FlowGate), springs layer | Authoritative |
| Copernicus Data Space STAC — Sentinel-2 L2A | acquisition/cloud metadata evidence | Authoritative EO |
| OpenStreetMap Overpass | waterway line geometry carrier (ODbL) | Secondary |

Flow status is **never** hardcoded: a segment becomes `VERIFIED_PERENNIAL` /
`VERIFIED_CURRENT` only from official spring-discharge history or active
hydrometric stations snapped within 500 m.

## Run it

```bash
docker compose up -d                 # PostGIS + Temporal + Temporal UI (:8233)
uv sync && uv pip install -e .
uv run alembic upgrade head          # schemas raw/core/analytics/ops/audit
uv run python scripts/ingest_pilot.py    # live ingestion, northern pilot basin
uv run python scripts/stac_enrich.py     # Sentinel-2 metadata evidence
uv run python apps/worker/main.py &      # Temporal worker
uv run python scripts/run_research.py    # research run → scored targets
uv run uvicorn apps.api.main:app --port 8100 &
cd apps/web && pnpm install && pnpm dev  # map UI at :5173
```

Quality gates: `uv run ruff check .` · `uv run pyright src/goldflow apps` ·
`uv run pytest tests/ -m "not contract and not e2e"`.

## Research pipeline (per target)

spatial facts (PostGIS: upstream trace, lithology mix, fault distance,
confluences, sinuosity) → geology + hydrology agents propose cited evidence →
**critic raises objections (mandatory before scoring)** → pure feature builder
→ deterministic versioned scorer (`prospect-v1`) → guardrail policy engine
(flow gate, water quality, mining rights, protected areas) → state transition
→ ScoreSnapshot + MeasurementProposal + DecisionTrace persisted to audit
schema.

Submitting an assay (`POST /v1/assay-results`) creates ground-truth evidence
and deterministically re-scores the dependent target (AC-10).

## API highlights

`GET /v1/targets` (GeoJSON, ranked) · `GET /v1/targets/{id}/dossier` ·
`GET /v1/targets/{id}/trace` · `GET /v1/geo/segments` · `GET /v1/geo/springs` ·
`GET /v1/layers` · `POST /v1/research-runs` · `POST /v1/assay-results`.

## Honest limitations (MVP)

- Waterway geometry is OSM (official Israeli stream shapefile downloads sit
  behind an anti-bot wall); flow classification is fully official-data-driven.
- No DEM yet: slope is unset; trap features use sinuosity + confluence density.
- Sentinel-2 participation is catalogue-metadata evidence, not raster algebra.
- Score is a relative 0-100 heuristic, not a calibrated probability, and the
  lithology favorability table is versioned config awaiting expert review.
- LLM rationale enhancement is stubbed off; all agent output is deterministic
  and source-grounded (which also satisfies AC-08 trivially).
