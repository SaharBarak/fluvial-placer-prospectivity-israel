"""Repository integration tests against live PostGIS (PRD §18.1)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from goldflow.domain.evidence import (
    Evidence,
    EvidenceKind,
    EvidenceQuality,
    SourceRef,
)
from goldflow.domain.results import Ok
from goldflow.domain.values import (
    AuthorityClass,
    EvidenceId,
    Point2039,
    Probability,
    SourceId,
)
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.db.repositories import EvidenceRepository, SourceRepository
from goldflow.infrastructure.settings import load_settings

pytestmark = pytest.mark.integration


@pytest.fixture
async def session():
    engine = build_async_engine(load_settings())
    factory = build_session_factory(engine)
    async with factory() as db_session:
        yield db_session
        await db_session.rollback()
    await engine.dispose()


async def test_evidence_dedup_by_fingerprint(session) -> None:
    sources = SourceRepository(session)
    source_result = await sources.upsert_by_url(
        name="test source",
        kind="test",
        authority_class=AuthorityClass.SECONDARY,
        url=f"test://dedup/{uuid4()}",
        retrieval_method="test",
    )
    assert isinstance(source_result, Ok)
    repo = EvidenceRepository(session)
    ref = SourceRef(
        source_id=SourceId(source_result.value),
        authority=AuthorityClass.SECONDARY,
        reference="r1",
        retrieved_at_iso="2026-08-15T00:00:00+00:00",
    )

    def make(evidence_id: EvidenceId) -> Evidence:
        return Evidence(
            id=evidence_id,
            kind=EvidenceKind.HISTORICAL_REPORT,
            location=Point2039(200000.0, 750000.0),
            observed_value=None,
            claim="identical claim",
            confidence=Probability(0.5),
            quality=EvidenceQuality.MEDIUM,
            valid_time=None,
            source_ref=ref,
        )

    first = await repo.add(make(EvidenceId(uuid4())))
    second = await repo.add(make(EvidenceId(uuid4())))
    assert isinstance(first, Ok) and isinstance(second, Ok)
    assert first.value == second.value  # dedup invariant §18.2


async def test_geometries_valid_after_ingestion(session) -> None:
    invalid = (
        await session.execute(
            text(
                """
                SELECT count(*) FROM core.waterway_segment WHERE NOT ST_IsValid(geom)
                """
            )
        )
    ).scalar_one()
    assert invalid == 0

    srid = (
        await session.execute(
            text("SELECT DISTINCT ST_SRID(geom) FROM core.waterway_segment LIMIT 1")
        )
    ).scalar_one_or_none()
    assert srid in (None, 2039)
