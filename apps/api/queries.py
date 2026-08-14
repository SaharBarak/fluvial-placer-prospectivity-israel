"""Read-model queries: PostGIS → GeoJSON (EPSG:4326 at the API boundary)."""

from __future__ import annotations

import json
from typing import Any, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def targets_geojson(
    session: AsyncSession,
    min_score: float | None = None,
    states: list[str] | None = None,
) -> dict[str, Any]:
    conditions = ["1=1"]
    params: dict[str, Any] = {}
    if min_score is not None:
        conditions.append("ss.score >= :min_score")
        params["min_score"] = min_score
    if states:
        conditions.append("t.state = ANY(:states)")
        params["states"] = states
    result = await session.execute(
        text(
            f"""
            WITH latest AS (
                SELECT DISTINCT ON (target_id) target_id, score, uncertainty,
                       model_version, created_at
                FROM analytics.score_snapshot ORDER BY target_id, created_at DESC
            )
            SELECT t.id, ST_AsGeoJSON(ST_Transform(t.geom, 4326)) AS geom,
                   t.state, t.actionability, ss.score, ss.uncertainty,
                   ws.name AS segment_name, ws.flow_status, ws.flow_valid_until,
                   RANK() OVER (ORDER BY ss.score DESC NULLS LAST) AS rank
            FROM core.prospect_target t
            JOIN core.waterway_segment ws ON ws.id = t.waterway_segment_id
            LEFT JOIN latest ss ON ss.target_id = t.id
            WHERE {" AND ".join(conditions)}
            ORDER BY ss.score DESC NULLS LAST
            LIMIT 500
            """  # noqa: S608 — conditions are static fragments, values bound
        ),
        params,
    )
    features = [
        {
            "type": "Feature",
            "geometry": json.loads(row.geom),
            "properties": {
                "id": str(row.id),
                "state": row.state,
                "actionability": row.actionability,
                "score": row.score,
                "uncertainty": row.uncertainty,
                "segment_name": row.segment_name,
                "flow_status": row.flow_status,
                "rank": row.rank,
            },
        }
        for row in result
    ]
    return {"type": "FeatureCollection", "features": features}


async def segments_geojson(session: AsyncSession, flow_only: bool) -> dict[str, Any]:
    where = (
        "flow_status IN ('VERIFIED_PERENNIAL','VERIFIED_CURRENT')"
        if flow_only
        else "flow_status <> 'UNKNOWN'"
    )
    result = await session.execute(
        text(
            f"""
            SELECT id, name, flow_status, flow_confidence, length_m,
                   ST_AsGeoJSON(ST_Transform(ST_SimplifyPreserveTopology(geom, 15), 4326))
                   AS geom
            FROM core.waterway_segment WHERE {where}
            LIMIT 4000
            """  # noqa: S608 — static fragment
        )
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row.geom),
                "properties": {
                    "id": str(row.id),
                    "name": row.name,
                    "flow_status": row.flow_status,
                    "flow_confidence": row.flow_confidence,
                    "length_m": row.length_m,
                },
            }
            for row in result
        ],
    }


async def springs_geojson(session: AsyncSession) -> dict[str, Any]:
    result = await session.execute(
        text(
            """
            SELECT id, name, discharge_lps, observed_at,
                   ST_AsGeoJSON(ST_Transform(geom, 4326)) AS geom
            FROM core.spring LIMIT 2000
            """
        )
    )
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": json.loads(row.geom),
                "properties": {
                    "id": str(row.id),
                    "name": row.name,
                    "discharge_lps": row.discharge_lps,
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                },
            }
            for row in result
        ],
    }


async def target_dossier(session: AsyncSession, target_id: str) -> dict[str, Any] | None:
    target = (
        await session.execute(
            text(
                """
                SELECT t.id, t.state, t.actionability,
                       ST_AsGeoJSON(ST_Transform(t.geom, 4326)) AS geom,
                       ws.id AS segment_id, ws.name AS segment_name, ws.flow_status,
                       ws.flow_confidence, ws.flow_valid_until, ws.length_m
                FROM core.prospect_target t
                JOIN core.waterway_segment ws ON ws.id = t.waterway_segment_id
                WHERE t.id = :tid
                """
            ),
            {"tid": target_id},
        )
    ).one_or_none()
    if target is None:
        return None

    score = (
        await session.execute(
            text(
                """
                SELECT model_version, score, uncertainty, components, created_at, run_id
                FROM analytics.score_snapshot WHERE target_id = :tid
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tid": target_id},
        )
    ).one_or_none()

    history = (
        await session.execute(
            text(
                """
                SELECT score, uncertainty, created_at FROM analytics.score_snapshot
                WHERE target_id = :tid ORDER BY created_at
                """
            ),
            {"tid": target_id},
        )
    ).all()

    trace = (
        await session.execute(
            text(
                """
                SELECT trace_id, run_id, state_before, state_after, evidence_ids,
                       derived_features, objections, rationale_summary, output_hash,
                       scoring_model_version, created_at
                FROM audit.decision_trace WHERE target_id = :tid
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tid": target_id},
        )
    ).one_or_none()

    evidence_rows = (
        await session.execute(
            text(
                """
                SELECT e.id, e.kind, e.claim, e.analyte, e.value, e.unit, e.confidence,
                       e.quality, e.authority, e.source_reference, e.created_at,
                       s.name AS source_name, s.url AS source_url, s.license
                FROM core.evidence e
                JOIN raw.source_document s ON s.id = e.source_id
                WHERE e.id IN (
                    WITH latest_trace AS (
                        SELECT evidence_ids FROM audit.decision_trace
                        WHERE target_id = :tid
                        ORDER BY created_at DESC LIMIT 1
                    )
                    SELECT (jsonb_array_elements_text(evidence_ids->'ids'))::uuid
                    FROM latest_trace
                )
                ORDER BY e.created_at
                """
            ),
            {"tid": target_id},
        )
    ).all()

    guardrails = (
        await session.execute(
            text(
                """
                SELECT DISTINCT ON (policy_id) policy_id, status, reason_code,
                       remediation, expires_at, created_at
                FROM audit.guardrail_event WHERE target_id = :tid
                ORDER BY policy_id, created_at DESC
                """
            ),
            {"tid": target_id},
        )
    ).all()

    proposal = (
        await session.execute(
            text(
                """
                SELECT kind, eig_score, expected_uncertainty_reduction, decision_impact,
                       normalized_cost, actionability, rationale
                FROM analytics.measurement_proposal WHERE target_id = :tid
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"tid": target_id},
        )
    ).one_or_none()

    return {
        "id": str(target.id),
        "geometry": json.loads(target.geom),
        "state": target.state,
        "actionability": target.actionability,
        "waterway": {
            "segment_id": str(target.segment_id),
            "name": target.segment_name,
            "flow_status": target.flow_status,
            "flow_confidence": target.flow_confidence,
            "flow_valid_until": (
                target.flow_valid_until.isoformat() if target.flow_valid_until else None
            ),
            "length_m": target.length_m,
        },
        "score": (
            {
                "model_version": score.model_version,
                "value": score.score,
                "uncertainty": score.uncertainty,
                "components": score.components.get("components", []),
                "created_at": score.created_at.isoformat(),
                "run_id": str(score.run_id) if score.run_id else None,
            }
            if score
            else None
        ),
        "score_history": [
            {"score": h.score, "uncertainty": h.uncertainty, "at": h.created_at.isoformat()}
            for h in history
        ],
        "evidence": [
            {
                "id": str(e.id),
                "kind": e.kind,
                "claim": e.claim,
                "measurement": (
                    {"analyte": e.analyte, "value": e.value, "unit": e.unit}
                    if e.analyte
                    else None
                ),
                "confidence": e.confidence,
                "quality": e.quality,
                "authority": e.authority,
                "source": {
                    "name": e.source_name,
                    "url": e.source_url,
                    "license": e.license,
                    "reference": e.source_reference,
                },
            }
            for e in evidence_rows
        ],
        "objections": (
            cast(dict[str, Any], trace.objections or {}).get("objections", [])
            if trace
            else []
        ),
        "guardrails": [
            {
                "policy_id": g.policy_id,
                "status": g.status,
                "reason_code": g.reason_code,
                "remediation": g.remediation,
                "expires_at": g.expires_at.isoformat() if g.expires_at else None,
            }
            for g in guardrails
        ],
        "next_measurement": (
            {
                "kind": proposal.kind,
                "eig_score": proposal.eig_score,
                "expected_uncertainty_reduction": proposal.expected_uncertainty_reduction,
                "decision_impact": proposal.decision_impact,
                "normalized_cost": proposal.normalized_cost,
                "actionability": proposal.actionability,
                "rationale": proposal.rationale,
            }
            if proposal
            else None
        ),
        "trace": (
            {
                "trace_id": str(trace.trace_id),
                "run_id": str(trace.run_id),
                "state_before": trace.state_before,
                "state_after": trace.state_after,
                "derived_features": cast(
                    dict[str, Any], trace.derived_features or {}
                ).get("features", {}),
                "rationale_summary": trace.rationale_summary,
                "output_hash": trace.output_hash,
                "scoring_model_version": trace.scoring_model_version,
                "created_at": trace.created_at.isoformat(),
            }
            if trace
            else None
        ),
    }
