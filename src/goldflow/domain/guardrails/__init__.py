"""Guardrail policy engine (PRD §15): separate from scoring.

A geologically interesting target can be BLOCKED. BLOCK dominates any field
action proposal but never erases the scientific ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from goldflow.domain.hydrology import FlowGatePass, FlowObservation, WaterwaySegment
from goldflow.domain.hydrology import evaluate_flow_gate as _flow_gate
from goldflow.domain.results import Ok
from goldflow.domain.targets import Actionability
from goldflow.domain.values import EvidenceId, PolicyId

GuardrailStatus = Literal["ALLOW", "WARN", "REVIEW", "BLOCK"]


class GuardrailReason(StrEnum):
    FLOW_NOT_VERIFIED = "FLOW_NOT_VERIFIED"
    FLOW_EVIDENCE_EXPIRED = "FLOW_EVIDENCE_EXPIRED"
    PROTECTED_AREA = "PROTECTED_AREA"
    WATER_QUALITY_ALERT = "WATER_QUALITY_ALERT"
    MINING_RIGHTS_REVIEW = "MINING_RIGHTS_REVIEW"
    FLOOD_WARNING = "FLOOD_WARNING"
    CONTAMINATION_HAZARD = "CONTAMINATION_HAZARD"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class GuardrailDecision:
    policy_id: PolicyId
    status: GuardrailStatus
    reason_code: GuardrailReason
    evidence_ids: tuple[EvidenceId, ...]
    expires_at: datetime | None = None
    remediation: str | None = None


@dataclass(frozen=True, slots=True)
class GuardrailInputs:
    """Facts the policy engine evaluates. All optional facts default to safe."""

    segment: WaterwaySegment
    flow_observations: tuple[FlowObservation, ...]
    now: datetime
    intersects_protected_area: bool = False
    protected_area_evidence: tuple[EvidenceId, ...] = ()
    water_quality_alert: bool = False
    water_quality_evidence: tuple[EvidenceId, ...] = ()
    contamination_flag: bool = False
    contamination_evidence: tuple[EvidenceId, ...] = ()
    flood_warning: bool = False


@dataclass(frozen=True, slots=True)
class GuardrailVerdict:
    decisions: tuple[GuardrailDecision, ...]
    actionability: Actionability
    flow_pass: FlowGatePass | None

    @property
    def field_clear(self) -> bool:
        return all(d.status not in ("BLOCK", "REVIEW") for d in self.decisions)


def evaluate_guardrails(inputs: GuardrailInputs) -> GuardrailVerdict:
    """Deterministic policy evaluation. Ordering fixed by policy id."""
    decisions: list[GuardrailDecision] = []

    flow_result = _flow_gate(inputs.segment, inputs.flow_observations, inputs.now)
    flow_pass: FlowGatePass | None
    match flow_result:
        case Ok(gate_pass):
            flow_pass = gate_pass
            decisions.append(
                GuardrailDecision(
                    policy_id=PolicyId("flow-gate"),
                    status="ALLOW",
                    reason_code=GuardrailReason.NONE,
                    evidence_ids=(),
                    expires_at=gate_pass.valid_until,
                )
            )
        case _:
            flow_pass = None
            decisions.append(
                GuardrailDecision(
                    policy_id=PolicyId("flow-gate"),
                    status="BLOCK",
                    reason_code=GuardrailReason.FLOW_NOT_VERIFIED,
                    evidence_ids=(),
                    remediation="נדרשת ראיית זרימה עדכנית למקטע",
                )
            )

    if inputs.intersects_protected_area:
        decisions.append(
            GuardrailDecision(
                policy_id=PolicyId("protected-areas"),
                status="REVIEW",
                reason_code=GuardrailReason.PROTECTED_AREA,
                evidence_ids=inputs.protected_area_evidence,
                remediation="דיגום פיזי מחייב בחינת הרשאה מפורשת",
            )
        )

    if inputs.water_quality_alert:
        decisions.append(
            GuardrailDecision(
                policy_id=PolicyId("water-quality"),
                status="BLOCK",
                reason_code=GuardrailReason.WATER_QUALITY_ALERT,
                evidence_ids=inputs.water_quality_evidence,
                remediation="אין להיכנס/לטבול במקטע המושפע",
            )
        )

    if inputs.contamination_flag:
        decisions.append(
            GuardrailDecision(
                policy_id=PolicyId("contamination"),
                status="WARN",
                reason_code=GuardrailReason.CONTAMINATION_HAZARD,
                evidence_ids=inputs.contamination_evidence,
            )
        )

    if inputs.flood_warning:
        decisions.append(
            GuardrailDecision(
                policy_id=PolicyId("flood"),
                status="BLOCK",
                reason_code=GuardrailReason.FLOOD_WARNING,
                evidence_ids=(),
                remediation="יש להמתין לסיום התרעת שיטפון/מזג אוויר",
            )
        )

    # Mineral rights: extraction-oriented action always requires permit review
    # in Israel (Mining Ordinance; PRD §15).
    decisions.append(
        GuardrailDecision(
            policy_id=PolicyId("mining-rights"),
            status="REVIEW",
            reason_code=GuardrailReason.MINING_RIGHTS_REVIEW,
            evidence_ids=(),
            remediation="איסוף/כרייה מחייבים היתר; מיפוי מחקרי מותר",
        )
    )

    statuses = {d.status for d in decisions}
    if "BLOCK" in statuses:
        actionability = Actionability.BLOCKED
    elif "REVIEW" in statuses:
        actionability = Actionability.PERMIT_REQUIRED
    elif "WARN" in statuses:
        actionability = Actionability.OBSERVE_ONLY
    else:
        actionability = Actionability.SAMPLE_ALLOWED_UNKNOWN

    return GuardrailVerdict(
        decisions=tuple(sorted(decisions, key=lambda d: d.policy_id)),
        actionability=actionability,
        flow_pass=flow_pass,
    )
