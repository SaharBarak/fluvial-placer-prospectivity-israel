"""Temporal worker hosting the research workflow and its activities."""

from __future__ import annotations

import asyncio

from temporalio.client import Client
from temporalio.worker import Worker

from goldflow.application.workflows.research import (
    TASK_QUEUE,
    ProspectResearchWorkflow,
    act_research_segment,
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
        workflows=[ProspectResearchWorkflow],
        activities=[act_set_run_state, act_select_segments, act_research_segment],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
