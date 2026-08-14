"""Temporal workflow (PRD §8.3): deterministic orchestration only.

All I/O lives in activities. The workflow sequences the run state machine and
fans out per-segment research activities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from temporalio import activity, workflow

TASK_QUEUE = "goldflow-research"


@dataclass
class ResearchCommand:
    run_id: str
    max_targets: int = 25
    flow_statuses: tuple[str, ...] = ("VERIFIED_PERENNIAL", "VERIFIED_CURRENT")


@dataclass
class ResearchOutcomeSummary:
    run_id: str
    targets: list[dict[str, Any]]
    failed_segments: list[str]


# --- Activities (imperative shell; implemented against the DB) ---


@activity.defn
async def act_set_run_state(run_id: str, state: str) -> None:
    from goldflow.application.workflows.runtime import set_run_state  # noqa: PLC0415

    await set_run_state(run_id, state)


@activity.defn
async def act_select_segments(flow_statuses: list[str], max_targets: int) -> list[str]:
    from goldflow.application.workflows.runtime import select_segments  # noqa: PLC0415

    return await select_segments(tuple(flow_statuses), max_targets)


@activity.defn
async def act_research_segment(segment_id: str, run_id: str) -> dict[str, Any]:
    from goldflow.application.workflows.runtime import research_segment  # noqa: PLC0415

    return await research_segment(segment_id, run_id)


# --- Workflow (deterministic) ---


@workflow.defn
class ProspectResearchWorkflow:
    @workflow.run
    async def run(self, cmd: ResearchCommand) -> ResearchOutcomeSummary:
        timeout = timedelta(minutes=5)

        await workflow.execute_activity(
            act_set_run_state,
            args=[cmd.run_id, "DISCOVERING"],
            start_to_close_timeout=timeout,
        )
        segments: list[str] = await workflow.execute_activity(
            act_select_segments,
            args=[list(cmd.flow_statuses), cmd.max_targets],
            start_to_close_timeout=timeout,
        )
        await workflow.execute_activity(
            act_set_run_state,
            args=[cmd.run_id, "ANALYZING"],
            start_to_close_timeout=timeout,
        )

        outcomes: list[dict[str, Any]] = []
        failed: list[str] = []
        for segment_id in segments:
            result: dict[str, Any] = await workflow.execute_activity(
                act_research_segment,
                args=[segment_id, cmd.run_id],
                start_to_close_timeout=timeout,
            )
            if result.get("ok"):
                outcomes.append(result)
            else:
                failed.append(segment_id)

        for state in ("SCORING", "PUBLISHING", "COMPLETED"):
            await workflow.execute_activity(
                act_set_run_state,
                args=[cmd.run_id, state],
                start_to_close_timeout=timeout,
            )
        return ResearchOutcomeSummary(
            run_id=cmd.run_id, targets=outcomes, failed_segments=failed
        )
