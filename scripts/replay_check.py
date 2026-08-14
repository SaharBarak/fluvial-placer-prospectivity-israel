"""AC-13: deterministic replay of a completed research workflow from history."""

from __future__ import annotations

import asyncio
import sys

from temporalio.client import Client
from temporalio.worker import Replayer

from goldflow.application.workflows.research import ProspectResearchWorkflow
from goldflow.infrastructure.settings import load_settings


async def main() -> int:
    settings = load_settings()
    client = await Client.connect(
        settings.temporal_address, namespace=settings.temporal_namespace
    )
    replayed = 0
    async for workflow in client.list_workflows(
        'WorkflowType="ProspectResearchWorkflow" AND ExecutionStatus="Completed"'
    ):
        handle = client.get_workflow_handle(workflow.id, run_id=workflow.run_id)
        history = await handle.fetch_history()
        replayer = Replayer(workflows=[ProspectResearchWorkflow])
        await replayer.replay_workflow(history)  # raises on nondeterminism
        replayed += 1
        print(f"replayed OK: {workflow.id}")
    if replayed == 0:
        print("no completed workflows found", file=sys.stderr)
        return 1
    print(f"AC-13 satisfied: {replayed} workflow(s) replayed with zero divergence")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
