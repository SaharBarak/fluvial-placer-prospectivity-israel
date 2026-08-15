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


@activity.defn
async def act_refresh_ingestion() -> dict[str, Any]:
    from goldflow.application.workflows.runtime import refresh_ingestion  # noqa: PLC0415

    return await refresh_ingestion()


@activity.defn
async def act_run_calibration() -> dict[str, Any]:
    from goldflow.application.workflows.runtime import run_calibration  # noqa: PLC0415

    return await run_calibration()


@activity.defn
async def act_create_run_record(run_id: str, executor: str, max_targets: int) -> None:
    from goldflow.application.workflows.runtime import create_run_record  # noqa: PLC0415

    await create_run_record(run_id, executor, max_targets)


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


@workflow.defn
class IngestRefreshWorkflow:
    """Scheduled: re-derive flow classification from live official sources.

    Flow evidence expires; without this refresh the FlowGate goes dark and
    every target degrades to BLOCKED_NO_FLOW — by design, not by accident.
    """

    @workflow.run
    async def run(self) -> dict[str, Any]:
        return await workflow.execute_activity(
            act_refresh_ingestion, start_to_close_timeout=timedelta(minutes=20)
        )


@workflow.defn
class ScheduledResearchWorkflow:
    """Scheduled: full research pass over verified-flow segments."""

    @workflow.run
    async def run(self) -> ResearchOutcomeSummary:
        run_id = str(workflow.uuid4())  # deterministic under replay
        await workflow.execute_activity(
            act_create_run_record,
            args=[run_id, "temporal-schedule", 30],
            start_to_close_timeout=timedelta(minutes=2),
        )
        return await workflow.execute_child_workflow(
            ProspectResearchWorkflow.run,
            ResearchCommand(run_id=run_id, max_targets=30),
            id=f"research-{run_id}",
        )


@workflow.defn
class CalibrationWorkflow:
    """Scheduled: field labels → calibration report → CANDIDATE weight set."""

    @workflow.run
    async def run(self) -> dict[str, Any]:
        return await workflow.execute_activity(
            act_run_calibration, start_to_close_timeout=timedelta(minutes=10)
        )
