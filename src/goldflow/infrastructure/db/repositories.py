"""Repositories: ORM rows ↔ frozen domain objects (PRD §11.4-11.5).

All methods return Result; SQLAlchemy exceptions are caught at this boundary
and converted to typed DatabaseError.
"""

from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

from geoalchemy2.shape import to_shape
from shapely.geometry import Point as ShapelyPoint
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from goldflow.domain.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceQuality,
    Measurement,
    SourceRef,
)
from goldflow.domain.hydrology import FlowStatus, WaterwaySegment
from goldflow.domain.results import DatabaseError, Err, Ok, Result
from goldflow.domain.scoring import ScoreSnapshot
from goldflow.domain.targets import Actionability, ProspectTarget, TargetState
from goldflow.domain.trace import DecisionTrace
from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Point2039,
    Probability,
    Score,
    SourceId,
    TargetId,
    WaterwayId,
    WaterwaySegmentId,
    utc_now,
)
from goldflow.infrastructure.db.models import (
    DecisionTraceRow,
    EvidenceRow,
    GuardrailEventRow,
    ProspectTargetRow,
    ResearchRunRow,
    ScoreSnapshotRow,
    SourceDocumentRow,
    WaterwaySegmentRow,
)


def _db_err(operation: str, exc: SQLAlchemyError) -> Err[DatabaseError]:
    return Err(DatabaseError(code="DB_ERROR", message=f"{operation}: {exc}"))


class SourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_by_url(
        self,
        *,
        name: str,
        kind: str,
        authority_class: AuthorityClass,
        url: str,
        retrieval_method: str,
        license_text: str | None = None,
        checksum: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Result[SourceId, DatabaseError]:
        try:
            existing = (
                await self._session.execute(
                    select(SourceDocumentRow).where(SourceDocumentRow.url == url)
                )
            ).scalar_one_or_none()
            if existing is not None:
                if checksum and existing.checksum != checksum:
                    existing.checksum = checksum
                    existing.version = str(int(existing.version) + 1)
                    existing.retrieved_at = utc_now()
                return Ok(SourceId(existing.id))
            row = SourceDocumentRow(
                id=uuid4(),
                name=name,
                kind=kind,
                authority_class=authority_class.value,
                license=license_text,
                url=url,
                retrieval_method=retrieval_method,
                retrieved_at=utc_now(),
                checksum=checksum,
                version="1",
                meta=meta or {},
            )
            self._session.add(row)
            await self._session.flush()
            return Ok(SourceId(row.id))
        except SQLAlchemyError as exc:
            return _db_err("source.upsert", exc)


def _segment_from_row(row: WaterwaySegmentRow) -> WaterwaySegment:
    return WaterwaySegment(
        id=WaterwaySegmentId(row.id),
        waterway_id=WaterwayId(row.waterway_id),
        name=row.name,
        flow_status=FlowStatus(row.flow_status),
        flow_confidence=Probability.clamped(row.flow_confidence),
        flow_valid_until=row.flow_valid_until,
        length_m=row.length_m,
    )


class SegmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self, segment_id: WaterwaySegmentId
    ) -> Result[WaterwaySegment, DatabaseError]:
        try:
            row = (
                await self._session.execute(
                    select(WaterwaySegmentRow).where(WaterwaySegmentRow.id == segment_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return Err(DatabaseError(code="NOT_FOUND", message=str(segment_id)))
            return Ok(_segment_from_row(row))
        except SQLAlchemyError as exc:
            return _db_err("segment.get", exc)

    async def list_by_flow(
        self, statuses: tuple[FlowStatus, ...], limit: int = 500
    ) -> Result[tuple[WaterwaySegment, ...], DatabaseError]:
        try:
            rows = (
                (
                    await self._session.execute(
                        select(WaterwaySegmentRow)
                        .where(
                            WaterwaySegmentRow.flow_status.in_([s.value for s in statuses])
                        )
                        .order_by(WaterwaySegmentRow.length_m.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
            return Ok(tuple(_segment_from_row(r) for r in rows))
        except SQLAlchemyError as exc:
            return _db_err("segment.list_by_flow", exc)


def _evidence_from_row(row: EvidenceRow) -> Evidence:
    location: Point2039 | None = None
    if row.geom is not None:
        shape = cast(ShapelyPoint, to_shape(row.geom))
        location = Point2039(shape.x, shape.y)
    measurement: Measurement | None = None
    if row.analyte is not None and row.value is not None and row.unit is not None:
        measurement = Measurement(
            analyte=row.analyte,
            value=row.value,
            unit=row.unit,
            detection_limit=row.detection_limit,
            below_detection=row.below_detection,
        )
    return Evidence(
        id=EvidenceId(row.id),
        kind=EvidenceKind(row.kind),
        location=location,
        observed_value=measurement,
        claim=row.claim,
        confidence=Probability.clamped(row.confidence),
        quality=EvidenceQuality(row.quality),
        valid_time=None,
        source_ref=SourceRef(
            source_id=SourceId(row.source_id),
            authority=AuthorityClass(row.authority),
            reference=row.source_reference,
            retrieved_at_iso=row.created_at.isoformat(),
        ),
        contamination_risk=(
            Probability.clamped(row.contamination_risk)
            if row.contamination_risk is not None
            else None
        ),
    )


class EvidenceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, item: Evidence) -> Result[EvidenceId, DatabaseError]:
        """Insert with dedup-by-fingerprint: identical evidence returns existing id."""
        try:
            fingerprint = item.fingerprint()
            existing = (
                await self._session.execute(
                    select(EvidenceRow.id).where(EvidenceRow.fingerprint == fingerprint)
                )
            ).scalar_one_or_none()
            if existing is not None:
                return Ok(EvidenceId(existing))
            row = EvidenceRow(
                id=item.id,
                kind=item.kind.value,
                geom=(
                    f"SRID=2039;POINT({item.location.x} {item.location.y})"
                    if item.location
                    else None
                ),
                analyte=item.observed_value.analyte if item.observed_value else None,
                value=item.observed_value.value if item.observed_value else None,
                unit=item.observed_value.unit if item.observed_value else None,
                detection_limit=(
                    item.observed_value.detection_limit if item.observed_value else None
                ),
                below_detection=(
                    item.observed_value.below_detection if item.observed_value else False
                ),
                claim=item.claim,
                confidence=item.confidence.value,
                quality=item.quality.value,
                source_id=item.source_ref.source_id,
                source_reference=item.source_ref.reference,
                authority=item.source_ref.authority.value,
                contamination_risk=(
                    item.contamination_risk.value if item.contamination_risk else None
                ),
                fingerprint=fingerprint,
                created_at=utc_now(),
            )
            self._session.add(row)
            await self._session.flush()
            return Ok(EvidenceId(row.id))
        except SQLAlchemyError as exc:
            return _db_err("evidence.add", exc)

    async def near_segment(
        self, segment_id: WaterwaySegmentId, radius_m: float = 3000.0
    ) -> Result[tuple[Evidence, ...], DatabaseError]:
        try:
            # Ground-truth assays bind tightly to their own segment (200 m);
            # regional evidence (geology, RS, water quality) joins at radius_m.
            id_rows = await self._session.execute(
                text(
                    """
                    SELECT e.id FROM core.evidence e
                    JOIN core.waterway_segment ws ON ws.id = CAST(:sid AS uuid)
                    WHERE e.geom IS NOT NULL
                      AND ST_DWithin(
                            e.geom, ws.geom,
                            CASE WHEN e.kind = 'ASSAY_RESULT'
                                 THEN CAST(:assay_radius AS float8)
                                 ELSE CAST(:radius AS float8) END)
                    ORDER BY e.created_at DESC
                    """
                ),
                {"sid": str(segment_id), "radius": radius_m, "assay_radius": 200.0},
            )
            ids = [row[0] for row in id_rows]
            if not ids:
                return Ok(())
            rows = (
                (
                    await self._session.execute(
                        select(EvidenceRow)
                        .where(EvidenceRow.id.in_(ids))
                        # Newest first: merge dedupe by (kind, reference) keeps the
                        # first occurrence, so the freshest wording supersedes
                        # legacy rows for the same source feature.
                        .order_by(EvidenceRow.created_at.desc())
                    )
                )
                .scalars()
                .all()
            )
            return Ok(tuple(_evidence_from_row(r) for r in rows))
        except SQLAlchemyError as exc:
            return _db_err("evidence.near_segment", exc)

    async def get_many(
        self, ids: tuple[EvidenceId, ...]
    ) -> Result[tuple[Evidence, ...], DatabaseError]:
        try:
            rows = (
                (
                    await self._session.execute(
                        select(EvidenceRow).where(EvidenceRow.id.in_(list(ids)))
                    )
                )
                .scalars()
                .all()
            )
            return Ok(tuple(_evidence_from_row(r) for r in rows))
        except SQLAlchemyError as exc:
            return _db_err("evidence.get_many", exc)


def _target_from_row(
    row: ProspectTargetRow, score: ScoreSnapshotRow | None = None
) -> ProspectTarget:
    shape = cast(ShapelyPoint, to_shape(row.geom))
    return ProspectTarget(
        id=TargetId(row.id),
        waterway_segment_id=WaterwaySegmentId(row.waterway_segment_id),
        location=Point2039(shape.x, shape.y),
        state=TargetState(row.state),
        score=Score(score.score) if score else None,
        uncertainty=score.uncertainty if score else None,
        actionability=Actionability(row.actionability),
    )


class TargetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, target_id: TargetId) -> Result[ProspectTarget, DatabaseError]:
        try:
            row = (
                await self._session.execute(
                    select(ProspectTargetRow).where(ProspectTargetRow.id == target_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return Err(DatabaseError(code="NOT_FOUND", message=str(target_id)))
            score = (
                await self._session.execute(
                    select(ScoreSnapshotRow)
                    .where(ScoreSnapshotRow.target_id == target_id)
                    .order_by(ScoreSnapshotRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            return Ok(_target_from_row(row, score))
        except SQLAlchemyError as exc:
            return _db_err("target.get", exc)

    async def upsert_for_segment(
        self, segment_id: WaterwaySegmentId, location: Point2039
    ) -> Result[ProspectTarget, DatabaseError]:
        """One CANDIDATE target per segment in MVP; idempotent."""
        try:
            row = (
                await self._session.execute(
                    select(ProspectTargetRow).where(
                        ProspectTargetRow.waterway_segment_id == segment_id
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                return Ok(_target_from_row(row))
            now = utc_now()
            row = ProspectTargetRow(
                id=uuid4(),
                waterway_segment_id=segment_id,
                geom=f"SRID=2039;POINT({location.x} {location.y})",
                state=TargetState.CANDIDATE.value,
                actionability=Actionability.OBSERVE_ONLY.value,
                created_at=now,
                updated_at=now,
            )
            self._session.add(row)
            await self._session.flush()
            # Fresh rows still hold the WKT literal, not a WKBElement — build directly.
            return Ok(
                ProspectTarget(
                    id=TargetId(row.id),
                    waterway_segment_id=WaterwaySegmentId(row.waterway_segment_id),
                    location=location,
                    state=TargetState(row.state),
                    actionability=Actionability(row.actionability),
                )
            )
        except SQLAlchemyError as exc:
            return _db_err("target.upsert_for_segment", exc)

    async def save_state(
        self, target: ProspectTarget
    ) -> Result[None, DatabaseError]:
        try:
            row = (
                await self._session.execute(
                    select(ProspectTargetRow).where(ProspectTargetRow.id == target.id)
                )
            ).scalar_one_or_none()
            if row is None:
                return Err(DatabaseError(code="NOT_FOUND", message=str(target.id)))
            row.state = target.state.value
            row.actionability = target.actionability.value
            row.updated_at = utc_now()
            await self._session.flush()
            return Ok(None)
        except SQLAlchemyError as exc:
            return _db_err("target.save_state", exc)

    async def list_scored(
        self, limit: int = 200
    ) -> Result[tuple[tuple[ProspectTarget, ScoreSnapshotRow | None], ...], DatabaseError]:
        try:
            rows = (
                (
                    await self._session.execute(
                        select(ProspectTargetRow).order_by(ProspectTargetRow.created_at)
                    )
                )
                .scalars()
                .all()
            )
            out: list[tuple[ProspectTarget, ScoreSnapshotRow | None]] = []
            for row in rows[:limit]:
                score = (
                    await self._session.execute(
                        select(ScoreSnapshotRow)
                        .where(ScoreSnapshotRow.target_id == row.id)
                        .order_by(ScoreSnapshotRow.created_at.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                out.append((_target_from_row(row, score), score))
            return Ok(tuple(out))
        except SQLAlchemyError as exc:
            return _db_err("target.list_scored", exc)


class ScoreRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_snapshot(
        self, snapshot: ScoreSnapshot, run_id: UUID | None
    ) -> Result[UUID, DatabaseError]:
        try:
            row = ScoreSnapshotRow(
                id=uuid4(),
                target_id=snapshot.target_id,
                run_id=run_id,
                model_version=snapshot.model_version,
                score=snapshot.score.value,
                uncertainty=snapshot.uncertainty,
                components={
                    "components": [
                        {
                            "feature": c.feature,
                            "family": c.family.value,
                            "raw_normalized": c.raw_normalized,
                            "weight": c.weight,
                            "contribution": c.contribution,
                            "evidence_ids": [str(e) for e in c.evidence_ids],
                        }
                        for c in snapshot.components
                    ]
                },
                created_at=utc_now(),
            )
            self._session.add(row)
            await self._session.flush()
            return Ok(row.id)
        except SQLAlchemyError as exc:
            return _db_err("score.add_snapshot", exc)


class TraceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, trace: DecisionTrace) -> Result[UUID, DatabaseError]:
        try:
            row = DecisionTraceRow(
                trace_id=trace.trace_id,
                run_id=trace.run_id,
                target_id=trace.target_id,
                state_before=trace.state_before,
                state_after=trace.state_after,
                evidence_ids={"ids": [str(e) for e in trace.evidence_ids]},
                tool_calls={
                    "calls": [
                        {
                            "tool": t.tool,
                            "request": t.canonical_request,
                            "response_ref": t.response_ref,
                            "status": t.status,
                            "latency_ms": t.latency_ms,
                        }
                        for t in trace.tool_calls
                    ]
                },
                derived_features={"features": dict(trace.derived_features)},
                objections={
                    "objections": [
                        {"kind": o.kind, "severity": o.severity, "statement": o.statement}
                        for o in trace.objections
                    ]
                },
                scoring_model_version=trace.scoring_model_version,
                prompt_hashes={"hashes": list(trace.prompt_hashes)},
                model_ids={"ids": list(trace.model_ids)},
                rationale_summary=trace.rationale_summary,
                output_hash=trace.output_hash,
                created_at=trace.created_at,
            )
            self._session.add(row)
            await self._session.flush()
            return Ok(row.trace_id)
        except SQLAlchemyError as exc:
            return _db_err("trace.add", exc)


class RunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        run_id: UUID,
        scope: dict[str, Any],
        source_snapshot_id: str,
        code_commit: str | None,
        budget: dict[str, Any],
    ) -> Result[UUID, DatabaseError]:
        try:
            row = ResearchRunRow(
                id=run_id,
                state="CREATED",
                scope=scope,
                source_snapshot_id=source_snapshot_id,
                code_commit=code_commit,
                budget=budget,
                started_at=utc_now(),
            )
            self._session.add(row)
            await self._session.flush()
            return Ok(row.id)
        except SQLAlchemyError as exc:
            return _db_err("run.create", exc)

    async def set_state(
        self, run_id: UUID, state: str, error: str | None = None
    ) -> Result[None, DatabaseError]:
        try:
            row = (
                await self._session.execute(
                    select(ResearchRunRow).where(ResearchRunRow.id == run_id)
                )
            ).scalar_one_or_none()
            if row is None:
                return Err(DatabaseError(code="NOT_FOUND", message=str(run_id)))
            row.state = state
            row.error = error
            if state in ("COMPLETED", "FAILED", "CANCELLED"):
                row.finished_at = utc_now()
            await self._session.flush()
            return Ok(None)
        except SQLAlchemyError as exc:
            return _db_err("run.set_state", exc)


class GuardrailEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_many(
        self,
        target_id: TargetId,
        run_id: UUID | None,
        decisions: tuple[Any, ...],
    ) -> Result[int, DatabaseError]:
        try:
            for decision in decisions:
                self._session.add(
                    GuardrailEventRow(
                        id=uuid4(),
                        run_id=run_id,
                        target_id=target_id,
                        policy_id=str(decision.policy_id),
                        status=decision.status,
                        reason_code=decision.reason_code.value,
                        evidence_ids={"ids": [str(e) for e in decision.evidence_ids]},
                        expires_at=decision.expires_at,
                        remediation=decision.remediation,
                        created_at=utc_now(),
                    )
                )
            await self._session.flush()
            return Ok(len(decisions))
        except SQLAlchemyError as exc:
            return _db_err("guardrail.add_many", exc)
