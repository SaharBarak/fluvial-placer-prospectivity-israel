"""Bootstrap ingestion for the northern pilot region (PRD §3.2)."""

from __future__ import annotations

import asyncio
import sys

from goldflow.application.services.ingestion import IngestionService
from goldflow.domain.results import Err, Ok
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.gsi import GsiArcGisAdapter
from goldflow.infrastructure.http import FetchClient, HttpBudget
from goldflow.infrastructure.osm import OverpassAdapter
from goldflow.infrastructure.settings import load_settings
from goldflow.infrastructure.water_authority import WaterAuthorityAdapter

# lon_min, lat_min, lon_max, lat_max — Upper Galilee + Golan + Kishon headwaters
PILOT_BBOX = (35.05, 32.85, 35.90, 33.35)


async def main() -> int:
    settings = load_settings()
    engine = build_async_engine(settings)
    sessions = build_session_factory(engine)
    async with FetchClient(
        budget=HttpBudget(max_requests=settings.run_http_budget),
        cache_dir=settings.object_store_root / "http-cache",
    ) as client:
        osm = OverpassAdapter(client)
        water = WaterAuthorityAdapter(client, settings.datagov_root)
        gsi = GsiArcGisAdapter(client, settings.gsi_arcgis_root)
        async with sessions() as session:
            service = IngestionService(session, osm, water, gsi)
            result = await service.ingest_pilot(PILOT_BBOX)
            match result:
                case Ok(report):
                    print(  # noqa: T201
                        f"segments={report.segments} springs={report.springs} "
                        f"stations={report.stations} geology={report.geology_units} "
                        f"faults={report.faults} verified_flow={report.flow_upgraded_segments}"
                    )
                    return 0
                case Err(error):
                    print(f"ingestion failed: {error}", file=sys.stderr)  # noqa: T201
                    return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
