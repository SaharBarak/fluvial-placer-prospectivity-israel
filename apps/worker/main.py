"""Temporal worker hosting the research workflow and its activities."""

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from goldflow.application.workflows.research import (
    TASK_QUEUE,
    CalibrationWorkflow,
    IngestRefreshWorkflow,
    ProspectResearchWorkflow,
    ScheduledResearchWorkflow,
    act_create_run_record,
    act_refresh_ingestion,
    act_research_segment,
    act_run_calibration,
    act_select_segments,
    act_set_run_state,
)
from goldflow.infrastructure.settings import load_settings


async def main() -> None:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    worker = Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[
            ProspectResearchWorkflow,
            ScheduledResearchWorkflow,
            IngestRefreshWorkflow,
            CalibrationWorkflow,
        ],
        activities=[
            act_set_run_state,
            act_select_segments,
            act_research_segment,
            act_refresh_ingestion,
            act_run_calibration,
            act_create_run_record,
        ],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
