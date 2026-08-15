"""One-time backfill: Hebrew formation display names from GSI layer 5.

Existing core.geological_unit rows were ingested English-first into both
``description`` and ``lithology``. The new split keeps ``lithology`` English
(favorability keywords match it) and makes ``description`` the Hebrew display
name. This script fetches name_heb per feature and updates description only.
Idempotent: re-running rewrites the same values.
"""

from __future__ import annotations

import asyncio

from sqlalchemy import text

from goldflow.domain.results import Err, Ok
from goldflow.infrastructure.db.engine import build_async_engine, build_session_factory
from goldflow.infrastructure.gsi import GsiArcGisAdapter
from goldflow.infrastructure.http import FetchClient, HttpBudget
from goldflow.infrastructure.settings import load_settings

PILOT_BBOX = (35.05, 32.85, 35.90, 33.35)
FORMATIONS_LAYER = 5


async def main() -> int:
    settings = load_settings()
    async with FetchClient(budget=HttpBudget(max_requests=50), cache_dir=None) as client:
        gsi = GsiArcGisAdapter(client, settings.gsi_arcgis_root)
        result = await gsi.query_layer(FORMATIONS_LAYER, bbox_4326=PILOT_BBOX)
        match result:
            case Err(error):
                print(f"GSI fetch failed: {error.code} {error.message}")
                return 1
            case Ok(features):
                pass

    names = {
        f"gsi-formation/{f.feature_ref}": str(f.properties.get("name_heb") or "")
        for f in features
        if f.properties.get("name_heb")
    }
    print(f"fetched {len(features)} formations, {len(names)} with Hebrew names")

    engine = build_async_engine(settings)
    sessions = build_session_factory(engine)
    updated = 0
    async with sessions() as session:
        for unit_ref, name_heb in names.items():
            outcome = await session.execute(
                text(
                    "UPDATE core.geological_unit SET description = :heb "
                    "WHERE unit_ref = :ref AND description IS DISTINCT FROM :heb"
                ),
                {"heb": name_heb, "ref": unit_ref},
            )
            updated += outcome.rowcount or 0
        await session.commit()
    await engine.dispose()
    print(f"updated {updated} geological units with Hebrew display names")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
