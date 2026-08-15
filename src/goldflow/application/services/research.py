"""Target research pipeline (PRD §8, §23.2).

Per segment: spatial facts → geology/hydrology agents → commit evidence →
critic (mandatory, AC-06) → features → deterministic score → guardrails →
state transition → persist snapshot, proposals, trace, guardrail events.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from goldflow.agents.critic import critique_target
from goldflow.agents.geology import analyze_geology
from goldflow.agents.hydrology import analyze_hydrology, flow_observations_for_segment
from goldflow.domain.evidence import Evidence
from goldflow.domain.features import EvidenceBundle, SpatialContext, build_target_features
from goldflow.domain.guardrails import GuardrailInputs, evaluate_guardrails
from goldflow.domain.planning import choose_next_measurement
from goldflow.domain.results import Err, Ok, Result
from goldflow.domain.scoring import score_target
from goldflow.domain.targets import (
    Actionability,
    ProspectTarget,
    TargetState,
    promote_to_field_ready,
    transition_target,
)
from goldflow.domain.trace import DecisionTrace, ObjectionRef
from goldflow.domain.values import (
    EvidenceId,
    Point2039,
    RunId,
    SourceId,
    TraceId,
    WaterwaySegmentId,
    utc_now,
)
from goldflow.infrastructure.db.models import MeasurementProposalRow
from goldflow.infrastructure.db.repositories import (
    EvidenceRepository,
    GuardrailEventRepository,
    ScoreRepository,
    SegmentRepository,
    TargetRepository,
    TraceRepository,
)
from goldflow.infrastructure.db.spatial import SpatialQueryService


@dataclass(frozen=True, slots=True)
class TargetResearchOutcome:
    target_id: str
    segment_name: str | None
    state: str
    score: float
    uncertainty: float
    objections: int
    evidence_count: int


@dataclass(frozen=True, slots=True)
class ResearchError:
    code: str
    message: str


class TargetResearchService:
    def __init__(
        self,
        session: AsyncSession,
        gsi_source_id: SourceId,
        water_source_id: SourceId,
    ) -> None:
        self._session = session
        self._segments = SegmentRepository(session)
        self._targets = TargetRepository(session)
        self._evidence = EvidenceRepository(session)
        self._scores = ScoreRepository(session)
        self._traces = TraceRepository(session)
        self._guardrails = GuardrailEventRepository(session)
        self._spatial = SpatialQueryService(session)
        self._gsi_source_id = gsi_source_id
        self._water_source_id = water_source_id

    async def research_segment(
        self, segment_id: WaterwaySegmentId, run_id: RunId
    ) -> Result[TargetResearchOutcome, ResearchError]:
        segment_result = await self._segments.get(segment_id)
        match segment_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(segment):
                pass

        facts_result = await self._spatial.facts_for_segment(segment_id)
        match facts_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(facts):
                pass

        midpoint_result = await self._spatial.midpoint_2039(segment_id)
        match midpoint_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok((mid_x, mid_y)):
                midpoint = Point2039(mid_x, mid_y)

        target_result = await self._targets.upsert_for_segment(segment_id, midpoint)
        match target_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(target):
                pass

        # --- ANALYZING: geology + hydrology agents propose evidence ---
        geology_artifact = analyze_geology(facts, self._gsi_source_id, midpoint)
        hydrology_artifact = analyze_hydrology(
            segment, facts, self._water_source_id, midpoint
        )

        committed: list[Evidence] = []
        id_remap: dict[EvidenceId, EvidenceId] = {}
        for artifact in (geology_artifact, hydrology_artifact):
            for item in artifact.proposed_evidence:
                added = await self._evidence.add(item)
                match added:
                    case Ok(evidence_id):
                        id_remap[item.id] = evidence_id
                        committed.append(
                            item if evidence_id == item.id else _rekey(item, evidence_id)
                        )
                    case Err():
                        continue

        # Merge previously committed evidence near the segment (assays, remote
        # sensing, earlier runs) so ground truth always reaches the scorer.
        # A failure here would leave the transaction aborted — fail loudly.
        nearby_result = await self._evidence.near_segment(segment_id)
        match nearby_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(nearby):
                # Dedupe by (kind, source reference): the same source feature
                # enters the bundle once; agent-proposed wording wins.
                seen_refs = {(e.kind, e.source_ref.reference) for e in committed}
                known_ids = {e.id for e in committed}
                for item in nearby:
                    key = (item.kind, item.source_ref.reference)
                    if item.id in known_ids or key in seen_refs:
                        continue
                    seen_refs.add(key)
                    committed.append(item)

        # --- CRITIQUING: mandatory critic pass (AC-06) ---
        critic_artifact = critique_target(segment, facts, tuple(committed))

        # --- SCORING: freeze features, deterministic score ---
        lithology_ids = tuple(
            sorted(
                (e.id for e in committed if e.kind.value == "GEOLOGICAL_UNIT"), key=str
            )
        )
        fault_ids = tuple(
            sorted(
                (e.id for e in committed if e.kind.value == "STRUCTURAL_FEATURE"), key=str
            )
        )
        spatial_context = SpatialContext(
            upstream_lithologies=facts.upstream_lithologies,
            lithology_evidence_ids=lithology_ids,
            nearest_fault_distance=facts.nearest_fault_distance,
            fault_evidence_ids=fault_ids,
            upstream_length_m=facts.upstream_length_m,
            segment_slope_pct=None,
            confluence_count=facts.confluence_count,
            sinuosity=facts.sinuosity,
        )
        flow_observations = flow_observations_for_segment(segment, self._water_source_id)
        bundle = EvidenceBundle(
            target_id=target.id,
            segment=segment,
            spatial=spatial_context,
            evidence=tuple(committed),
            flow_observations=flow_observations,
        )
        features_result = build_target_features(bundle)
        match features_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(features):
                pass
        score_result = score_target(features)
        match score_result:
            case Err(error):
                return Err(ResearchError(code=error.code, message=error.message))
            case Ok(snapshot):
                pass

        # --- Guardrails + state transition ---
        verdict = evaluate_guardrails(
            GuardrailInputs(
                segment=segment,
                flow_observations=flow_observations,
                now=utc_now(),
                water_quality_alert=facts.water_quality_alert_nearby,
            )
        )
        state_before = target.state
        researched = transition_target(target, TargetState.RESEARCH_READY)
        target = researched.value if isinstance(researched, Ok) else target
        target = _apply_actionability(target, verdict.actionability)

        if verdict.flow_pass is not None and verdict.field_clear:
            promoted = promote_to_field_ready(target, verdict.flow_pass, True)
            if isinstance(promoted, Ok):
                target = promoted.value
        elif verdict.flow_pass is None:
            blocked = transition_target(target, TargetState.BLOCKED_NO_FLOW)
            if isinstance(blocked, Ok):
                target = blocked.value
        else:
            observed = transition_target(target, TargetState.OBSERVATION_ONLY)
            if isinstance(observed, Ok):
                target = observed.value

        # Field-validation loop (PRD §14.1): assay ground truth closes the loop.
        validation_state = _assay_validation_state(tuple(committed))
        if validation_state is not None:
            validated = transition_target(target, validation_state)
            if isinstance(validated, Ok):
                target = validated.value

        await self._targets.save_state(target)
        await self._scores.add_snapshot(snapshot, UUID(str(run_id)))
        await self._guardrails.add_many(target.id, UUID(str(run_id)), verdict.decisions)

        proposal = choose_next_measurement(
            target_id=target.id,
            uncertainty=snapshot.uncertainty,
            score_value=snapshot.score.value,
            actionability=target.actionability,
            has_geochemistry=any(
                e.kind.value in ("GEOCHEMICAL_SAMPLE", "ASSAY_RESULT") for e in committed
            ),
            has_current_flow=verdict.flow_pass is not None,
        )
        self._session.add(
            MeasurementProposalRow(
                id=uuid4(),
                target_id=target.id,
                run_id=UUID(str(run_id)),
                kind=proposal.kind.value,
                eig_score=proposal.eig_score,
                expected_uncertainty_reduction=proposal.expected_uncertainty_reduction,
                decision_impact=proposal.decision_impact,
                normalized_cost=proposal.normalized_cost,
                actionability=proposal.actionability.value,
                rationale=proposal.rationale,
                created_at=utc_now(),
            )
        )

        trace = DecisionTrace(
            trace_id=TraceId(uuid4()),
            run_id=run_id,
            target_id=target.id,
            state_before=state_before.value,
            state_after=target.state.value,
            evidence_ids=tuple(e.id for e in committed),
            tool_calls=(),
            derived_features=tuple(
                (f.name, round(f.normalized, 4)) for f in features.features
            ),
            objections=tuple(
                ObjectionRef(
                    kind=o.kind.value, severity=o.severity.value, statement=o.statement
                )
                for o in critic_artifact.objections
            ),
            scoring_model_version=snapshot.model_version,
            prompt_hashes=(),
            model_ids=(),
            rationale_summary=" | ".join(
                (
                    geology_artifact.rationale_summary,
                    hydrology_artifact.rationale_summary,
                    critic_artifact.rationale_summary,
                )
            ),
            created_at=utc_now(),
        ).with_output_hash()
        await self._traces.add(trace)
        await self._session.commit()

        return Ok(
            TargetResearchOutcome(
                target_id=str(target.id),
                segment_name=segment.name,
                state=target.state.value,
                score=snapshot.score.value,
                uncertainty=snapshot.uncertainty,
                objections=len(critic_artifact.objections),
                evidence_count=len(committed),
            )
        )


# Versioned validation thresholds (validation-v1): Au above this level in stream
# sediment is anomalous relative to typical <5 ppb background and confirms the
# target hypothesis; magnitude interpretation stays medium/background-relative.
AU_VALIDATION_PPB = 50.0
MIN_NEGATIVE_ASSAYS = 2  # a single below-detection assay is not falsification


def _assay_validation_state(evidence: tuple[Evidence, ...]) -> TargetState | None:
    """Pure mapping of assay ground truth to a validation transition (§14.1)."""
    assays = [
        e
        for e in evidence
        if e.kind.value == "ASSAY_RESULT"
        and e.observed_value is not None
        and e.observed_value.analyte.lower() in ("au", "gold")
    ]
    if not assays:
        return None
    detected = [
        a
        for a in assays
        if a.observed_value is not None
        and not a.observed_value.below_detection
        and a.observed_value.value >= AU_VALIDATION_PPB
    ]
    if detected:
        return TargetState.VALIDATED_POSITIVE
    below = [
        a
        for a in assays
        if a.observed_value is not None and a.observed_value.below_detection
    ]
    if len(below) >= MIN_NEGATIVE_ASSAYS and len(below) == len(assays):
        return TargetState.VALIDATED_NEGATIVE
    return None


def _rekey(item: Evidence, new_id: EvidenceId) -> Evidence:
    return Evidence(
        id=new_id,
        kind=item.kind,
        location=item.location,
        observed_value=item.observed_value,
        claim=item.claim,
        confidence=item.confidence,
        quality=item.quality,
        valid_time=item.valid_time,
        source_ref=item.source_ref,
        contamination_risk=item.contamination_risk,
    )


def _apply_actionability(target: ProspectTarget, actionability: Actionability) -> ProspectTarget:
    return ProspectTarget(
        id=target.id,
        waterway_segment_id=target.waterway_segment_id,
        location=target.location,
        state=target.state,
        score=target.score,
        uncertainty=target.uncertainty,
        actionability=actionability,
    )
