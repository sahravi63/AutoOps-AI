"""
AutoOps AI — Dependency-Aware Graph Executor
=============================================
Replaces the empty graph.py stub with a real DAG runner.

Key improvements over the original sequential loop:
  1. Reads `depends_on` from each step — steps only run after all
     their dependencies have COMPLETED successfully.
  2. Steps with no unmet deps in the same wave run in parallel
     (asyncio.gather).
  3. If a dependency FAILED, all downstream steps are SKIPPED
     rather than silently running with bad inputs.
  4. Placeholder resolution (${stepN.key}) is applied just-in-time
     from actual upstream step outputs.
  5. High-risk plans still halt on first failure (original behaviour
     preserved via halt_on_fail flag).

Usage:
    from app.agents.graph import GraphExecutor
    graph_exec = GraphExecutor()
    steps = await graph_exec.run(plan, executor)
"""

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Set

from app.agents.executor_agent import ExecutorAgent, resolve_placeholders
from app.models.workflow_model import AgentStep
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _build_dep_map(steps_cfg: List[Dict[str, Any]]) -> Dict[int, List[int]]:
    deps: Dict[int, List[int]] = {}
    for cfg in steps_cfg:
        sn = cfg.get("step_number", 0)
        raw = cfg.get("depends_on", [])
        deps[sn] = list(raw) if isinstance(raw, (list, tuple)) else []
    return deps


def _topological_waves(
    steps_cfg: List[Dict[str, Any]],
    dep_map: Dict[int, List[int]],
) -> List[List[Dict[str, Any]]]:
    """Group steps into parallel waves respecting depends_on."""
    resolved: Set[int] = set()
    waves: List[List[Dict]] = []
    remaining = list(steps_cfg)
    max_iters = len(steps_cfg) + 1

    while remaining and max_iters > 0:
        max_iters -= 1
        wave: List[Dict] = []
        still_waiting: List[Dict] = []

        for cfg in remaining:
            sn = cfg.get("step_number", 0)
            if all(d in resolved for d in dep_map.get(sn, [])):
                wave.append(cfg)
            else:
                still_waiting.append(cfg)

        if not wave:
            logger.warning(
                "[GraphExecutor] Cycle detected — executing remaining steps sequentially"
            )
            waves.append(remaining)
            break

        waves.append(wave)
        for cfg in wave:
            resolved.add(cfg.get("step_number", 0))
        remaining = still_waiting

    return waves


def _make_skipped_step(cfg: Dict[str, Any], failed_deps: List[int]) -> AgentStep:
    return AgentStep(
        step_number=cfg.get("step_number", 0),
        agent=cfg.get("agent", "executor"),
        tool=cfg.get("tool", ""),
        action=cfg.get("action", ""),
        input_data={"parameters": cfg.get("parameters", {})},
        status="failed",
        error=f"Skipped — upstream steps {failed_deps} failed",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )


class GraphExecutor:
    """Dependency-aware plan executor using topological wave scheduling."""

    async def run(
        self,
        plan: Dict[str, Any],
        executor: ExecutorAgent,
    ) -> List[AgentStep]:
        steps_cfg = plan.get("steps", [])
        risk_level = plan.get("risk_level", "low")
        halt_on_fail = (risk_level == "high")

        if not steps_cfg:
            logger.warning("[GraphExecutor] Plan has no steps.")
            return []

        dep_map = _build_dep_map(steps_cfg)
        waves = _topological_waves(steps_cfg, dep_map)

        logger.info(
            f"[GraphExecutor] {len(steps_cfg)} steps | {len(waves)} wave(s) | "
            f"risk={risk_level}"
        )

        step_outputs: Dict[int, Dict[str, Any]] = {}
        failed_step_nums: Set[int] = set()
        all_steps: List[AgentStep] = []

        for wave_idx, wave in enumerate(waves):
            runnable: List[Dict] = []

            for cfg in wave:
                sn = cfg.get("step_number", 0)
                failed_deps = [d for d in dep_map.get(sn, []) if d in failed_step_nums]
                if failed_deps:
                    skipped = _make_skipped_step(cfg, failed_deps)
                    all_steps.append(skipped)
                    failed_step_nums.add(sn)
                    logger.warning(f"[GraphExecutor] Step {sn} SKIPPED (deps {failed_deps} failed)")
                else:
                    runnable.append(cfg)

            if not runnable:
                continue

            logger.info(
                f"[GraphExecutor] Wave {wave_idx+1}/{len(waves)}: "
                f"running steps {[c.get('step_number') for c in runnable]} in parallel"
            )

            async def _exec_one(cfg: Dict) -> AgentStep:
                resolved_params = resolve_placeholders(
                    cfg.get("parameters", {}), step_outputs
                )
                step = AgentStep(
                    step_number=cfg.get("step_number", 0),
                    agent=cfg.get("agent", "executor"),
                    tool=cfg.get("tool", ""),
                    action=cfg.get("action", "execute"),
                    input_data={"parameters": resolved_params},
                )
                await asyncio.sleep(0.05)
                return await executor.execute_step(step)

            results: List[AgentStep] = await asyncio.gather(
                *[_exec_one(cfg) for cfg in runnable]
            )

            for result_step in results:
                all_steps.append(result_step)
                sn = result_step.step_number
                step_outputs[sn] = result_step.output_data or {}

                if result_step.status == "failed":
                    failed_step_nums.add(sn)
                    if halt_on_fail:
                        logger.warning("[GraphExecutor] High-risk plan halted after failure")
                        executed = {s.step_number for s in all_steps}
                        for cfg in steps_cfg:
                            if cfg.get("step_number") not in executed:
                                all_steps.append(_make_skipped_step(cfg, [sn]))
                        return sorted(all_steps, key=lambda s: s.step_number)

        return sorted(all_steps, key=lambda s: s.step_number)
