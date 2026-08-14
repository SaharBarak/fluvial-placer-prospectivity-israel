"""GoldFlow API (PRD §12): query + command endpoints.

Commands are idempotent (Idempotency-Key) and audited; assay submission
triggers deterministic re-scoring of the dependent target (AC-10).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any, cast
from uuid import UUID, uuid4

from apps.api import queries
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from goldflow.application.workflows import runtime
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.gsi import ATTRIBUTION as GSI_ATTRIBUTION
from goldflow.infrastructure.gsi import GEOLOGY_SERVICE
from goldflow.infrastructure.osm import ATTRIBUTION as OSM_ATTRIBUTION
from goldflow.infrastructure.settings import load_settings

settings = load_settings()
_sessions: async_sessionmaker[AsyncSession] | None = None
_idempotency_seen: dict[str, dict[str, Any]] = {}


@asynccontextmanager  # pyright: ignore[reportDeprecated] — typeshed marks the bare form; usage is standard
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global _sessions  # noqa: PLW0603
    engine = build_async_engine(settings)
    _sessions = build_session_factory(engine)
    yield
    await engine.dispose()


app = FastAPI(title="GoldFlow Israel", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.api_cors_origins.split(","),
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_session() -> AsyncIterator[AsyncSession]:
    if _sessions is None:
        raise HTTPException(status_code=503, detail="not ready")
    async with _sessions() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


# --- Query API (§12.1) ---


@app.get("/v1/targets")
async def list_targets(
    session: SessionDep,
    min_score: Annotated[float | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
) -> dict[str, Any]:
    states = state.split(",") if state else None
    return await queries.targets_geojson(session, min_score, states)


@app.get("/v1/targets/{target_id}/dossier")
async def get_dossier(target_id: str, session: SessionDep) -> dict[str, Any]:
    dossier = await queries.target_dossier(session, target_id)
    if dossier is None:
        raise HTTPException(status_code=404, detail="target not found")
    return dossier


@app.get("/v1/targets/{target_id}/trace")
async def get_trace(target_id: str, session: SessionDep) -> dict[str, Any]:
    rows = (
        await session.execute(
            text(
                """
                SELECT trace_id, run_id, state_before, state_after, evidence_ids,
                       tool_calls, derived_features, objections, rationale_summary,
                       output_hash, scoring_model_version, created_at
                FROM audit.decision_trace WHERE target_id = :tid ORDER BY created_at
                """
            ),
            {"tid": target_id},
        )
    ).all()
    return {
        "target_id": target_id,
        "traces": [
            {
                "trace_id": str(r.trace_id),
                "run_id": str(r.run_id),
                "state_before": r.state_before,
                "state_after": r.state_after,
                "evidence_ids": cast(dict[str, Any], r.evidence_ids or {}).get("ids", []),
                "derived_features": cast(dict[str, Any], r.derived_features or {}).get(
                    "features", {}
                ),
                "objections": cast(dict[str, Any], r.objections or {}).get("objections", []),
                "rationale_summary": r.rationale_summary,
                "output_hash": r.output_hash,
                "scoring_model_version": r.scoring_model_version,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
    }


@app.get("/v1/layers")
async def list_layers() -> dict[str, Any]:
    return {
        "layers": [
            {
                "id": "gsi-geology",
                "title": "GSI geological map 1:200k (2014)",
                "type": "raster-export",
                "url_template": (
                    f"{settings.gsi_arcgis_root}/{GEOLOGY_SERVICE}/MapServer/export"
                ),
                "attribution": GSI_ATTRIBUTION,
            },
            {
                "id": "hydrology-segments",
                "title": "Waterway segments (flow-classified)",
                "type": "geojson",
                "url": "/v1/geo/segments",
                "attribution": OSM_ATTRIBUTION + " + Israel Water Authority",
            },
            {
                "id": "springs",
                "title": "Springs (Water Authority catalog)",
                "type": "geojson",
                "url": "/v1/geo/springs",
                "attribution": "Israel Water Authority / data.gov.il",
            },
            {
                "id": "targets",
                "title": "Prospect targets",
                "type": "geojson",
                "url": "/v1/targets",
                "attribution": "GoldFlow research runs",
            },
        ]
    }


@app.get("/v1/geo/segments")
async def geo_segments(
    session: SessionDep, flow_only: Annotated[bool, Query()] = False
) -> dict[str, Any]:
    return await queries.segments_geojson(session, flow_only)


@app.get("/v1/geo/springs")
async def geo_springs(session: SessionDep) -> dict[str, Any]:
    return await queries.springs_geojson(session)


@app.get("/v1/waterways/{segment_id}")
async def get_segment(segment_id: str, session: SessionDep) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT id, name, flow_status, flow_confidence, flow_valid_until,
                       length_m, source_feature_ref,
                       ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geom
                FROM core.waterway_segment WHERE id = :sid
                """
            ),
            {"sid": segment_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="segment not found")
    import json as _json  # noqa: PLC0415

    return {
        "id": str(row.id),
        "name": row.name,
        "flow_status": row.flow_status,
        "flow_confidence": row.flow_confidence,
        "flow_valid_until": (
            row.flow_valid_until.isoformat() if row.flow_valid_until else None
        ),
        "length_m": row.length_m,
        "source_feature_ref": row.source_feature_ref,
        "geometry": _json.loads(row.geom),
    }


@app.get("/v1/runs/{run_id}")
async def get_run(run_id: str, session: SessionDep) -> dict[str, Any]:
    row = (
        await session.execute(
            text(
                """
                SELECT id, state, scope, source_snapshot_id, code_commit, budget,
                       started_at, finished_at, error
                FROM ops.research_run WHERE id = :rid
                """
            ),
            {"rid": run_id},
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="run not found")
    return {
        "id": str(row.id),
        "state": row.state,
        "scope": row.scope,
        "source_snapshot_id": row.source_snapshot_id,
        "code_commit": row.code_commit,
        "budget": row.budget,
        "started_at": row.started_at.isoformat(),
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
    }


# --- Command API (§12.2) ---


class AssaySubmission(BaseModel):
    target_id: UUID
    analyte: str = Field(default="Au", max_length=16)
    value: float = Field(ge=0)
    unit: str = Field(default="ppb", max_length=16)
    lod: float | None = None
    below_detection: bool = False
    lab: str | None = None
    method: str | None = None
    lon: float | None = None
    lat: float | None = None


@app.post("/v1/assay-results", status_code=201)
async def submit_assay(
    submission: AssaySubmission,
    session: SessionDep,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, Any]:
    if idempotency_key and idempotency_key in _idempotency_seen:
        return _idempotency_seen[idempotency_key]

    target = (
        await session.execute(
            text(
                """
                SELECT t.id, t.waterway_segment_id,
                       ST_X(t.geom) AS x, ST_Y(t.geom) AS y
                FROM core.prospect_target t WHERE t.id = :tid
                """
            ),
            {"tid": str(submission.target_id)},
        )
    ).one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="target not found")

    source_id = (
        await session.execute(
            text(
                """
                INSERT INTO raw.source_document
                    (id, name, kind, authority_class, url, retrieval_method,
                     retrieved_at, version, meta)
                VALUES (:id, :name, 'field-assay', 'FIELD_GROUND_TRUTH', :url,
                        'manual-entry', now(), '1', '{}')
                RETURNING id
                """
            ),
            {
                "id": str(uuid4()),
                "name": f"Field assay {submission.lab or 'manual'}",
                "url": f"assay://{submission.target_id}/{uuid4()}",
            },
        )
    ).scalar_one()

    sample_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO core.field_sample
                (id, target_id, geom, medium, collected_at, permit_state)
            VALUES (:id, :tid,
                    ST_SetSRID(ST_MakePoint(:x, :y), 2039),
                    'stream_sediment', now(), 'UNKNOWN')
            """
        ),
        {"id": sample_id, "tid": str(submission.target_id), "x": target.x, "y": target.y},
    )
    await session.execute(
        text(
            """
            INSERT INTO core.assay_result
                (id, field_sample_id, analyte, value, unit, lod, lab, method, reported_at)
            VALUES (:id, :sid, :analyte, :value, :unit, :lod, :lab, :method, now())
            """
        ),
        {
            "id": str(uuid4()),
            "sid": sample_id,
            "analyte": submission.analyte,
            "value": submission.value,
            "unit": submission.unit,
            "lod": submission.lod,
            "lab": submission.lab,
            "method": submission.method,
        },
    )
    evidence_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO core.evidence
                (id, kind, geom, analyte, value, unit, detection_limit, below_detection,
                 claim, confidence, quality, source_id, source_reference, authority,
                 fingerprint, created_at)
            VALUES (:id, 'ASSAY_RESULT',
                    ST_SetSRID(ST_MakePoint(:x, :y), 2039),
                    :analyte, :value, :unit, :lod, :below,
                    :claim, 0.95, 'HIGH', :source_id, :ref, 'FIELD_GROUND_TRUTH',
                    :fp, now())
            """
        ),
        {
            "id": evidence_id,
            "x": target.x,
            "y": target.y,
            "analyte": submission.analyte,
            "value": submission.value,
            "unit": submission.unit,
            "lod": submission.lod,
            "below": submission.below_detection,
            "claim": (
                f"Field assay: {submission.analyte} = {submission.value} "
                f"{submission.unit}"
                + (f" (lab: {submission.lab})" if submission.lab else "")
            ),
            "source_id": source_id,
            "ref": f"sample/{sample_id}",
            "fp": str(uuid4()),
        },
    )
    await session.commit()

    # AC-10: assay evidence deterministically re-scores the dependent target.
    rescore_run_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO ops.research_run
                (id, state, scope, source_snapshot_id, budget, started_at)
            VALUES (:id, 'ANALYZING', :scope, :snapshot, '{}', now())
            """
        ),
        {
            "id": rescore_run_id,
            "scope": '{"trigger": "assay-submission"}',
            "snapshot": f"rescore-{rescore_run_id[:8]}",
        },
    )
    await session.commit()
    rescore = await runtime.research_segment(
        str(target.waterway_segment_id), rescore_run_id
    )
    await runtime.set_run_state(rescore_run_id, "COMPLETED")

    response = {
        "assay_evidence_id": evidence_id,
        "sample_id": sample_id,
        "rescore_run_id": rescore_run_id,
        "rescore": rescore,
    }
    if idempotency_key:
        _idempotency_seen[idempotency_key] = response
    return response


class ResearchRunRequest(BaseModel):
    max_targets: int = Field(default=30, ge=1, le=200)


@app.post("/v1/research-runs", status_code=202)
async def start_research_run(
    request: ResearchRunRequest, session: SessionDep
) -> dict[str, Any]:
    run_id = str(uuid4())
    await session.execute(
        text(
            """
            INSERT INTO ops.research_run
                (id, state, scope, source_snapshot_id, budget, started_at)
            VALUES (:id, 'CREATED', :scope, :snapshot, '{}', now())
            """
        ),
        {
            "id": run_id,
            "scope": f'{{"executor": "api", "max_targets": {request.max_targets}}}',
            "snapshot": f"snapshot-{run_id[:8]}",
        },
    )
    await session.commit()
    import asyncio  # noqa: PLC0415

    async def _execute() -> None:
        await runtime.set_run_state(run_id, "DISCOVERING")
        segments = await runtime.select_segments(
            ("VERIFIED_PERENNIAL", "VERIFIED_CURRENT"), request.max_targets
        )
        await runtime.set_run_state(run_id, "ANALYZING")
        for segment_id in segments:
            await runtime.research_segment(segment_id, run_id)
        for state in ("SCORING", "PUBLISHING", "COMPLETED"):
            await runtime.set_run_state(run_id, state)

    asyncio.get_running_loop().create_task(_execute())
    return {"run_id": run_id, "state": "CREATED"}


@app.get("/healthz")
async def healthz(session: SessionDep) -> dict[str, str]:
    await session.execute(text("SELECT 1"))
    return {"status": "ok"}
