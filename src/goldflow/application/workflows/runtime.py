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
    async with _session_factory()() as session:
        gsi_source = await _source_id(session, "egozi.gsi.gov.il")
        water_source = await _source_id(session, "data.gov.il")
        service = TargetResearchService(session, gsi_source, water_source)
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
