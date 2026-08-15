"""Activity runtime: process-wide engine and source-id resolution.

Shared by the Temporal worker and the in-process fallback runner so both paths
execute the identical research pipeline.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from goldflow.application.services.research import TargetResearchService
from goldflow.domain.results import Err, Ok
from goldflow.domain.values import RunId, SourceId, WaterwaySegmentId
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.settings import load_settings

_engine: AsyncEngine | None = None
_sessions: async_sessionmaker[AsyncSession] | None = None


def _session_factory() -> async_sessionmaker[AsyncSession]:
    global _engine, _sessions  # noqa: PLW0603 — process-wide connection pool
    if _sessions is None:
        _engine = build_async_engine(load_settings())
        _sessions = build_session_factory(_engine)
    return _sessions


async def _source_id(session: AsyncSession, url_fragment: str) -> SourceId:
    result = await session.execute(
        text("SELECT id FROM raw.source_document WHERE url LIKE :pattern LIMIT 1"),
        {"pattern": f"%{url_fragment}%"},
    )
    row = result.scalar_one()
    return SourceId(row)


PILOT_BBOX = (35.05, 32.85, 35.90, 33.35)


async def refresh_ingestion() -> dict[str, Any]:
    """Re-run source ingestion for the pilot region.

    Flow evidence carries expiry (90-180 d); this refresh is what keeps the
    FlowGate alive over time. Idempotent: existing features are skipped, flow
    classifications and validity windows are re-derived from current data.
    """
    from goldflow.application.services.ingestion import (  # noqa: PLC0415 — cycle guard
        IngestionService,
    )
    from goldflow.infrastructure.gsi import GsiArcGisAdapter  # noqa: PLC0415
    from goldflow.infrastructure.http import FetchClient, HttpBudget  # noqa: PLC0415
    from goldflow.infrastructure.osm import OverpassAdapter  # noqa: PLC0415
    from goldflow.infrastructure.water_authority import (  # noqa: PLC0415
        WaterAuthorityAdapter,
    )

    settings = load_settings()
    async with (
        FetchClient(
            budget=HttpBudget(max_requests=settings.run_http_budget),
            cache_dir=None,  # refresh must see current data, not cached snapshots
        ) as client,
        _session_factory()() as session,
    ):
        service = IngestionService(
            session,
            OverpassAdapter(client),
            WaterAuthorityAdapter(client, settings.datagov_root),
            GsiArcGisAdapter(client, settings.gsi_arcgis_root),
        )
        result = await service.ingest_pilot(PILOT_BBOX)
        match result:
            case Ok(report):
                return {
                    "ok": True,
                    "segments": report.segments,
                    "springs": report.springs,
                    "verified_flow": report.flow_upgraded_segments,
                }
            case Err(error):
                return {"ok": False, "error": str(error)}
    return {"ok": False, "error": "unreachable"}


async def run_calibration() -> dict[str, Any]:
    from goldflow.application.services.calibration import (  # noqa: PLC0415 — cycle guard
        CalibrationService,
    )

    async with _session_factory()() as session:
        result = await CalibrationService(session).run()
        match result:
            case Ok(report):
                return {
                    "ok": True,
                    "n_labels": report.n_labels,
                    "n_positive": report.n_positive,
                    "n_negative": report.n_negative,
                    "enrichment": report.enrichment,
                    "family_correlations": dict(report.family_correlations),
                    "fit_performed": report.fit_performed,
                    "candidate_weights": (
                        dict(report.candidate_weights)
                        if report.candidate_weights
                        else None
                    ),
                    "holdout_accuracy": report.holdout_accuracy,
                }
            case Err(error):
                return {"ok": False, "code": error.code, "message": error.message}
    return {"ok": False, "code": "UNREACHABLE", "message": "match exhausted"}


async def create_run_record(run_id: str, executor: str, max_targets: int) -> None:
    async with _session_factory()() as session:
        await session.execute(
            text(
                """
                INSERT INTO ops.research_run
                    (id, state, scope, source_snapshot_id, budget, started_at)
                VALUES (:id, 'CREATED', CAST(:scope AS jsonb), :snapshot,
                        '{}', now())
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {
                "id": run_id,
                "scope": (
                    f'{{"executor": "{executor}", "max_targets": {max_targets}}}'
                ),
                "snapshot": f"snapshot-{run_id[:8]}",
            },
        )
        await session.commit()


async def set_run_state(run_id: str, state: str) -> None:
    async with _session_factory()() as session:
        await session.execute(
            text("UPDATE ops.research_run SET state = :state WHERE id = :run_id"),
            {"state": state, "run_id": run_id},
        )
        if state in ("COMPLETED", "FAILED", "CANCELLED"):
            await session.execute(
                text("UPDATE ops.research_run SET finished_at = now() WHERE id = :run_id"),
                {"run_id": run_id},
            )
        await session.commit()


async def select_segments(flow_statuses: tuple[str, ...], max_targets: int) -> list[str]:
    async with _session_factory()() as session:
        result = await session.execute(
            text(
                """
                SELECT id FROM core.waterway_segment
                WHERE flow_status = ANY(:statuses) AND length_m > 500
                ORDER BY length_m DESC
                LIMIT :max_targets
                """
            ),
            {"statuses": list(flow_statuses), "max_targets": max_targets},
        )
        return [str(row[0]) for row in result]


async def research_segment(segment_id: str, run_id: str) -> dict[str, Any]:
    from goldflow.application.services.calibration import (  # noqa: PLC0415 — cycle guard
        load_active_model,
    )

    async with _session_factory()() as session:
        gsi_source = await _source_id(session, "egozi.gsi.gov.il")
        water_source = await _source_id(session, "data.gov.il")
        model = await load_active_model(session)
        service = TargetResearchService(session, gsi_source, water_source, model)
        outcome = await service.research_segment(
            WaterwaySegmentId(UUID(segment_id)), RunId(UUID(run_id))
        )
        match outcome:
            case Ok(value):
                return {
                    "ok": True,
                    "target_id": value.target_id,
                    "segment_name": value.segment_name,
                    "state": value.state,
                    "score": value.score,
                    "uncertainty": value.uncertainty,
                    "objections": value.objections,
                    "evidence_count": value.evidence_count,
                }
            case Err(error):
                return {"ok": False, "code": error.code, "message": error.message}
    return {"ok": False, "code": "UNREACHABLE", "message": "match exhausted"}
