"""Calibration service: field labels → calibration report → candidate model.

Reads validated targets with their latest score snapshots, rebuilds family
subscores from stored components, runs the pure calibration engine, and writes
a CANDIDATE weight set to ops.model_registry. Activation stays a human action
(PRD §15: nothing mutates the live score path silently).
"""

from __future__ import annotations

import json
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from goldflow.domain.learning import CalibrationReport, LabeledExample, calibrate
from goldflow.domain.results import Err, Ok, Result, ValidationError
from goldflow.domain.scoring import FeatureFamily, ScoringModel
from goldflow.domain.values import utc_now

CANDIDATE_VERSION_PREFIX = "prospect-cal"


def _family_subscores(components: list[dict[str, Any]]) -> tuple[float, float, float]:
    """Mean raw_normalized per core family — mirrors the scorer's subscore rule."""
    out: list[float] = []
    for family in (FeatureFamily.SOURCE_SYSTEM, FeatureFamily.TRANSPORT, FeatureFamily.TRAP):
        members = [
            float(c["raw_normalized"])
            for c in components
            if c.get("family") == family.value and float(c.get("contribution", 0)) >= 0
            and c.get("feature") not in ("evidence_quality_factor", "contamination_discount")
        ]
        out.append(sum(members) / len(members) if members else 0.0)
    return (out[0], out[1], out[2])


async def load_active_model(session: AsyncSession) -> ScoringModel:
    row = (
        await session.execute(
            text(
                """
                SELECT version, weights FROM ops.model_registry
                WHERE status = 'ACTIVE' AND kind = 'scoring-weights'
                ORDER BY activated_at DESC LIMIT 1
                """
            )
        )
    ).one_or_none()
    if row is None:
        return ScoringModel.baseline()
    weights = cast(dict[str, float], row.weights)
    return ScoringModel(
        version=str(row.version),
        weights=tuple(
            (FeatureFamily(name), float(value)) for name, value in sorted(weights.items())
        ),
    )


class CalibrationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self) -> Result[CalibrationReport, ValidationError]:
        rows = (
            await self._session.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT DISTINCT ON (target_id) target_id, score, components
                        FROM analytics.score_snapshot
                        ORDER BY target_id, created_at DESC
                    )
                    SELECT t.id, t.state, l.score, l.components
                    FROM core.prospect_target t
                    JOIN latest l ON l.target_id = t.id
                    ORDER BY t.created_at, t.id
                    """
                )
            )
        ).all()

        examples: list[LabeledExample] = []
        scores: list[tuple[float, bool]] = []
        for row in rows:
            positive = row.state == "VALIDATED_POSITIVE"
            validated = row.state in ("VALIDATED_POSITIVE", "VALIDATED_NEGATIVE")
            components = cast(dict[str, Any], row.components).get("components", [])
            scores.append((float(row.score), positive))
            if validated:
                examples.append(
                    LabeledExample(
                        subscores=_family_subscores(components), positive=positive
                    )
                )

        result = calibrate(tuple(examples), tuple(scores))
        match result:
            case Err(error):
                return Err(error)
            case Ok(report):
                pass

        if report.fit_performed and report.candidate_weights is not None:
            version = f"{CANDIDATE_VERSION_PREFIX}-{utc_now().strftime('%Y%m%d%H%M')}"
            await self._session.execute(
                text(
                    """
                    INSERT INTO ops.model_registry
                        (id, version, kind, weights, status, metrics, created_at)
                    VALUES (:id, :version, 'scoring-weights',
                            CAST(:weights AS jsonb), 'CANDIDATE',
                            CAST(:metrics AS jsonb), now())
                    ON CONFLICT (version) DO NOTHING
                    """
                ),
                {
                    "id": str(uuid4()),
                    "version": version,
                    "weights": json.dumps(dict(report.candidate_weights)),
                    "metrics": json.dumps(
                        {
                            "n_labels": report.n_labels,
                            "n_positive": report.n_positive,
                            "n_negative": report.n_negative,
                            "holdout_accuracy": report.holdout_accuracy,
                            "enrichment": report.enrichment,
                            "family_correlations": dict(report.family_correlations),
                        }
                    ),
                },
            )
            await self._session.commit()
        return Ok(report)
