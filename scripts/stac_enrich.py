"""Sentinel-2 STAC metadata enrichment (PRD §13.1, MVP slice).

Queries the Copernicus Data Space STAC catalogue for the pilot bbox and
attaches a REMOTE_SENSING evidence item to every verified-flow segment:
acquisition density and cloud statistics with STAC item lineage. No pixel is
ever interpreted as Au (AC-14).
"""

from __future__ import annotations

import asyncio
import statistics
import sys
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import text

from goldflow.domain.results import Err, Ok
from goldflow.domain.values import utc_now
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.http import FetchClient, HttpBudget
from goldflow.infrastructure.settings import load_settings
from goldflow.infrastructure.stac import StacAdapter

PILOT_BBOX = (35.05, 32.85, 35.90, 33.35)
LOOKBACK_DAYS = 90


async def main() -> int:
    settings = load_settings()
    engine = build_async_engine(settings)
    sessions = build_session_factory(engine)
    now = utc_now()
    date_from = (now - timedelta(days=LOOKBACK_DAYS)).date().isoformat()
    date_to = now.date().isoformat()

    async with FetchClient(
        budget=HttpBudget(max_requests=20),
        cache_dir=settings.object_store_root / "http-cache",
    ) as client:
        stac = StacAdapter(client, settings.stac_root)
        result = await stac.search_sentinel2(PILOT_BBOX, date_from, date_to, limit=100)
        match result:
            case Err(error):
                print(f"STAC failed: {error}", file=sys.stderr)
                return 1
            case Ok(items):
                pass

    clouds = [i.cloud_cover_pct for i in items if i.cloud_cover_pct is not None]
    median_cloud = statistics.median(clouds) if clouds else None
    item_refs = ",".join(i.item_id for i in items[:5])
    claim = (
        f"Sentinel-2 L2A coverage: {len(items)} scenes in {LOOKBACK_DAYS} d over pilot "
        f"basin; median cloud {median_cloud:.0f}%"
        if median_cloud is not None
        else f"Sentinel-2 L2A coverage: {len(items)} scenes in {LOOKBACK_DAYS} d"
    )

    async with sessions() as session:
        source_id = (
            await session.execute(
                text(
                    """
                    INSERT INTO raw.source_document
                        (id, name, kind, authority_class, url, retrieval_method,
                         retrieved_at, version, meta)
                    VALUES (:id, 'Copernicus Data Space STAC — Sentinel-2 L2A',
                            'stac-catalogue', 'AUTHORITATIVE',
                            'https://stac.dataspace.copernicus.eu/v1', 'stac-search',
                            now(), '1', '{}')
                    ON CONFLICT DO NOTHING
                    RETURNING id
                    """
                ),
                {"id": str(uuid4())},
            )
        ).scalar_one_or_none()
        if source_id is None:
            source_id = (
                await session.execute(
                    text(
                        "SELECT id FROM raw.source_document "
                        "WHERE url = 'https://stac.dataspace.copernicus.eu/v1' LIMIT 1"
                    )
                )
            ).scalar_one()

        inserted = await session.execute(
            text(
                """
                INSERT INTO core.evidence
                    (id, kind, geom, below_detection, claim, confidence, quality,
                     source_id, source_reference, authority, fingerprint, created_at)
                SELECT gen_random_uuid(), 'REMOTE_SENSING',
                       ST_LineInterpolatePoint(ws.geom, 0.5), false,
                       :claim, 0.7, 'MEDIUM', :source_id,
                       :refs, 'AUTHORITATIVE',
                       md5('stac-cover-' || ws.id::text || :date_to), now()
                FROM core.waterway_segment ws
                WHERE ws.flow_status IN ('VERIFIED_PERENNIAL', 'VERIFIED_CURRENT')
                ON CONFLICT (fingerprint) DO NOTHING
                """
            ),
            {
                "claim": claim,
                "source_id": str(source_id),
                "refs": f"stac-items:{item_refs}",
                "date_to": date_to,
            },
        )
        await session.commit()
        print(f"scenes={len(items)} median_cloud={median_cloud} evidence_rows={inserted.rowcount}")
    await engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
