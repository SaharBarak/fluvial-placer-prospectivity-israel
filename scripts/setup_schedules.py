"""Create/refresh the Temporal Schedules that make GoldFlow run continuously.

- ingest-refresh: every 24 h — re-derives flow classification from live
  official sources (flow evidence expires; this keeps the FlowGate alive).
- research: every 12 h — full research pass over verified-flow segments.
- calibration: every 24 h — field labels → report → CANDIDATE weight set.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleSpec,
)
from temporalio.service import RPCError

from goldflow.application.workflows.research import (
    TASK_QUEUE,
    CalibrationWorkflow,
    IngestRefreshWorkflow,
    ScheduledResearchWorkflow,
)
from goldflow.infrastructure.settings import load_settings

SCHEDULES: tuple[tuple[str, type, timedelta], ...] = (
    ("goldflow-ingest-refresh", IngestRefreshWorkflow, timedelta(hours=24)),
    ("goldflow-research", ScheduledResearchWorkflow, timedelta(hours=12)),
    ("goldflow-calibration", CalibrationWorkflow, timedelta(hours=24)),
)


async def main() -> int:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    for schedule_id, workflow_type, interval in SCHEDULES:
        handle = client.get_schedule_handle(schedule_id)
        try:
            await handle.delete()
            print(f"replaced existing schedule {schedule_id}")
        except RPCError:
            pass
        await client.create_schedule(
            schedule_id,
            Schedule(
                action=ScheduleActionStartWorkflow(
                    workflow_type.run,
                    id=f"{schedule_id}-run",
                    task_queue=TASK_QUEUE,
                ),
                spec=ScheduleSpec(intervals=[ScheduleIntervalSpec(every=interval)]),
            ),
        )
        print(f"schedule {schedule_id}: every {interval}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
