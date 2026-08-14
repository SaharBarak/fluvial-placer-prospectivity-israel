"""Start a research run: Temporal when reachable, else in-process fallback.

Both paths execute the identical activity implementations; the run manifest
records the executor used.
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from uuid import uuid4

from sqlalchemy import text

from goldflow.application.workflows import runtime
from goldflow.application.workflows.research import (
    TASK_QUEUE,
    ProspectResearchWorkflow,
    ResearchCommand,
)
from goldflow.infrastructure.settings import load_settings

MAX_TARGETS = 30


def _git_commit() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
            ).stdout.strip()
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


async def _create_run(run_id: str, executor: str) -> None:
    async with runtime._session_factory()() as session:
        await session.execute(
            text(
                """
                INSERT INTO ops.research_run
                    (id, state, scope, source_snapshot_id, code_commit, budget, started_at)
                VALUES
                    (:id, 'CREATED', :scope, :snapshot, :commit, :budget, now())
                """
            ),
            {
                "id": run_id,
                "scope": (
                    '{"pilot": "north-israel", "executor": "%s", "max_targets": %d}'
                    % (executor, MAX_TARGETS)
                ),
                "snapshot": f"snapshot-{run_id[:8]}",
                "commit": _git_commit(),
                "budget": '{"http": 500, "tokens": 0}',
            },
        )
        await session.commit()


async def _run_temporal(run_id: str) -> dict[str, object] | None:
    try:
        from temporalio.client import Client  # noqa: PLC0415 — optional dependency path

        settings = load_settings()
        client = await asyncio.wait_for(
            Client.connect(settings.temporal_address, namespace=settings.temporal_namespace),
            timeout=6.0,
        )
    except Exception as exc:
        print(f"temporal unavailable ({exc.__class__.__name__}); fallback", file=sys.stderr)
        return None
    handle = await client.start_workflow(
        ProspectResearchWorkflow.run,
        ResearchCommand(run_id=run_id, max_targets=MAX_TARGETS),
        id=f"research-{run_id}",
        task_queue=TASK_QUEUE,
    )
    result = await handle.result()
    return {"targets": result.targets, "failed": result.failed_segments}


async def _run_inprocess(run_id: str) -> dict[str, object]:
    await runtime.set_run_state(run_id, "DISCOVERING")
    segments = await runtime.select_segments(
        ("VERIFIED_PERENNIAL", "VERIFIED_CURRENT"), MAX_TARGETS
    )
    await runtime.set_run_state(run_id, "ANALYZING")
    outcomes: list[dict[str, object]] = []
    failed: list[str] = []
    for segment_id in segments:
        result = await runtime.research_segment(segment_id, run_id)
        (outcomes if result.get("ok") else failed).append(
            result if result.get("ok") else segment_id  # type: ignore[arg-type]
        )
    for state in ("SCORING", "PUBLISHING", "COMPLETED"):
        await runtime.set_run_state(run_id, state)
    return {"targets": outcomes, "failed": failed}


async def main() -> int:
    run_id = str(uuid4())
    use_temporal = "--no-temporal" not in sys.argv
    summary: dict[str, object] | None = None
    if use_temporal:
        await _create_run(run_id, "temporal")
        summary = await _run_temporal(run_id)
    if summary is None:
        await _create_run(run_id, "in-process") if not use_temporal else None
        summary = await _run_inprocess(run_id)
    targets = summary.get("targets") or []
    failed = summary.get("failed") or []
    print(f"run={run_id} targets={len(targets)} failed={len(failed)}")
    ranked = sorted(
        (t for t in targets if isinstance(t, dict)),
        key=lambda t: -float(t.get("score", 0)),
    )
    for target in ranked[:10]:
        print(
            f"  {target.get('score'):>6} u={target.get('uncertainty'):.2f} "
            f"{target.get('state'):<18} {target.get('segment_name')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
