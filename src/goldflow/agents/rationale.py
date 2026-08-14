"""Concise, source-grounded rationale summaries (PRD §9: no chain-of-thought)."""

from __future__ import annotations

from goldflow.domain.values import EvidenceId


def cite(summary: str, evidence_ids: tuple[EvidenceId, ...]) -> str:
    if not evidence_ids:
        return summary
    shorts = ", ".join(str(e)[:8] for e in evidence_ids[:5])
    suffix = f" [evidence: {shorts}{'…' if len(evidence_ids) > 5 else ''}]"
    return summary + suffix
