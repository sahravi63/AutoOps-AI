"""
AutoOps AI — Autonomous Agent Service
======================================
The CORE orchestration layer. Implements the full 5-step autonomy loop:

    THINK → PLAN → EXECUTE → REVIEW → UPDATE (retry if needed)

This is what makes AutoOps AI an autonomous system, NOT just a pipeline.
A pipeline runs once and returns whatever it gets.
An autonomous agent evaluates its own output, and self-corrects until
it either passes the quality check or exhausts its retry budget.

Loop behaviour:
  - Max 3 attempts per workflow
  - If reviewer returns passed=False, feedback is carried into next attempt
  - Memory is searched BEFORE planning (gives context from past workflows)
  - Memory is written AFTER a successful review (system learns over time)
"""

import asyncio
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.agents.executor_agent import ExecutorAgent
from app.agents.memory_agent import memory_agent
from app.agents.planner_agent import PlannerAgent
from app.agents.reviewer_agent import ReviewerAgent
from app.models.workflow_model import AgentStep, WorkflowResult
from app.utils.logger import get_logger

logger = get_logger(__name__)

MAX_LOOPS = 3          # Max self-correction attempts before delivering best result
PASS_THRESHOLD = True  # reviewer.review() returns {"passed": bool}


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — called by routes.py /workflow/run
# ─────────────────────────────────────────────────────────────────────────────

async def run_autonomous_workflow(
    task: str,
    context: Optional[Dict[str, Any]] = None,
    workflow_id: Optional[str] = None,
) -> WorkflowResult:
    """
    Run the full 5-step autonomous agent loop for a given task.

    Returns a WorkflowResult containing the plan, all executed steps,
    the final review, and metadata about how many loops were used.
    """

    workflow_id = workflow_id or str(uuid.uuid4())[:12]
    result = WorkflowResult(workflow_id=workflow_id, task=task)
    result.status = "running"

    logger.info(f"[AutoOpsAI] ═══════════════════════════════════════")
    logger.info(f"[AutoOpsAI] Workflow {workflow_id} | Task: {task[:80]}")
    logger.info(f"[AutoOpsAI] ═══════════════════════════════════════")

    planner  = PlannerAgent()
    executor = ExecutorAgent()
    reviewer = ReviewerAgent()

    # ── THINK: Search memory for similar past workflows ────────────────────
    logger.info(f"[THINK] Searching memory for similar workflows...")
    memory_hints = memory_agent.search(task, top_k=3)
    if memory_hints:
        logger.info(f"[THINK] Found {len(memory_hints)} relevant memories — informing planner")
    else:
        logger.info(f"[THINK] No relevant memories found — starting fresh")

    # ── AUTONOMY LOOP ─────────────────────────────────────────────────────
    feedback: str = ""           # Feedback from reviewer, carried across loops
    best_result: Optional[WorkflowResult] = None   # Best attempt so far

    for loop_num in range(1, MAX_LOOPS + 1):
        logger.info(f"[AutoOpsAI] ─── Loop {loop_num} of {MAX_LOOPS} ───")

        # ── PLAN ──────────────────────────────────────────────────────────
        logger.info(f"[PLAN] Generating execution plan...")
        try:
            plan = planner.plan(
                task=task,
                context=context,
                memory_hints=memory_hints,
                feedback=feedback,       # Empty on loop 1; filled on retries
            )
            logger.info(
                f"[PLAN] Ready — {len(plan.get('steps', []))} steps | "
                f"type={plan.get('workflow_type')} | risk={plan.get('risk_level')}"
            )
        except Exception as e:
            logger.error(f"[PLAN] Failed: {e}")
            result.status = "failed"
            result.review = {"passed": False, "summary": f"Planning failed: {e}"}
            result.completed_at = datetime.utcnow()
            return result

        result.plan = plan

        # ── EXECUTE ────────────────────────────────────────────────────────
        logger.info(f"[EXECUTE] Running {len(plan.get('steps', []))} steps...")
        try:
            steps: List[AgentStep] = await executor.execute_plan(plan)
            result.steps = steps
            completed = sum(1 for s in steps if s.status == "completed")
            failed    = sum(1 for s in steps if s.status == "failed")
            logger.info(f"[EXECUTE] Done — {completed} completed, {failed} failed")
        except Exception as e:
            logger.error(f"[EXECUTE] Fatal error: {e}")
            result.status = "failed"
            result.review = {"passed": False, "summary": f"Execution crashed: {e}"}
            result.completed_at = datetime.utcnow()
            return result

        # ── REVIEW ─────────────────────────────────────────────────────────
        logger.info(f"[REVIEW] Evaluating results...")
        try:
            review = reviewer.review(task, plan, steps)
            result.review = review
            passed     = review.get("passed", False)
            confidence = review.get("confidence", 0)
            summary    = review.get("summary", "")
            logger.info(
                f"[REVIEW] passed={passed} | confidence={confidence:.2f} | {summary[:80]}"
            )
        except Exception as e:
            logger.error(f"[REVIEW] Reviewer crashed: {e} — defaulting to retry")
            review  = {"passed": False, "confidence": 0, "summary": f"Review error: {e}",
                        "recommendations": ["Retry with improved plan"]}
            result.review = review
            passed = False

        # ── SNAPSHOT best attempt ──────────────────────────────────────────
        # Even if we don't pass, keep the best run so far
        if best_result is None or passed:
            best_result = WorkflowResult(
                workflow_id=workflow_id,
                task=task,
                plan=result.plan,
                steps=result.steps,
                review=result.review,
                status="completed" if passed else "partial",
            )

        # ── UPDATE / SELF-CORRECT ──────────────────────────────────────────
        if passed:
            logger.info(f"[UPDATE] Quality check PASSED on loop {loop_num} ✓")
            result.status = "completed"
            # Store successful pattern in memory so future runs benefit
            _store_memory(task, plan, review)
            break
        else:
            # Extract specific feedback for the next attempt
            recs = review.get("recommendations", [])
            issues = review.get("issues", [])
            feedback = "; ".join(recs + issues) or "Improve coverage and reliability of steps"
            logger.info(f"[UPDATE] Quality check FAILED — feedback: {feedback[:120]}")

            if loop_num < MAX_LOOPS:
                logger.info(f"[UPDATE] Starting loop {loop_num + 1} with targeted feedback...")
                await asyncio.sleep(0.5)  # Brief pause before retry
            else:
                logger.info(f"[UPDATE] Max loops ({MAX_LOOPS}) reached — delivering best attempt")
                result.status = "partial"
                if best_result:
                    result.plan  = best_result.plan
                    result.steps = best_result.steps
                    result.review = best_result.review

    result.completed_at = datetime.utcnow()

    # Add loop metadata to review for transparency
    result.review["loops_used"] = loop_num
    result.review["max_loops"]  = MAX_LOOPS

    logger.info(
        f"[AutoOpsAI] Workflow {workflow_id} DONE | "
        f"status={result.status} | loops={loop_num}"
    )
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Memory helper — store successful workflow patterns
# ─────────────────────────────────────────────────────────────────────────────

def _store_memory(task: str, plan: Dict[str, Any], review: Dict[str, Any]) -> None:
    """Store a successful workflow pattern in memory for future reference."""
    mem_update = review.get("memory_update", {})
    should_store = mem_update.get("store", True)

    if not should_store:
        return

    category = mem_update.get("category") or plan.get("workflow_type", "general")
    lesson   = mem_update.get("lesson")   or review.get("summary", "Workflow completed successfully")

    try:
        mem_id = memory_agent.store(
            category=category,
            problem=task,
            solution=lesson,
        )
        logger.info(f"[MEMORY] Stored pattern {mem_id} in category '{category}'")
    except Exception as e:
        logger.warning(f"[MEMORY] Could not store memory: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# Streaming entry point — yields SSE events, called by routes.py /workflow/stream
# ─────────────────────────────────────────────────────────────────────────────

async def run_autonomous_workflow_streaming(
    task: str,
    context: Optional[Dict[str, Any]] = None,
):
    """
    Generator version of run_autonomous_workflow.
    Yields (event_name, data_dict) tuples for Server-Sent Events.

    Usage in routes.py:
        async for event, data in run_autonomous_workflow_streaming(task):
            yield sse(event, data)
    """

    workflow_id = str(uuid.uuid4())[:12]
    planner  = PlannerAgent()
    executor = ExecutorAgent()
    reviewer = ReviewerAgent()

    yield ("start", {
        "workflow_id": workflow_id,
        "message": f"Starting autonomous workflow: {task[:60]}",
        "ts": datetime.utcnow().isoformat(),
    })

    # ── THINK ──────────────────────────────────────────────────────────────
    yield ("think", {"message": "Searching memory for similar workflows..."})
    memory_hints = memory_agent.search(task, top_k=3)
    yield ("memory_recall", {
        "count": len(memory_hints),
        "message": f"Found {len(memory_hints)} relevant memories" if memory_hints else "No prior memories — starting fresh",
        "hints": [h.get("document", "")[:100] for h in memory_hints],
    })
    await asyncio.sleep(0.2)

    feedback: str = ""
    final_review: Dict[str, Any] = {}
    final_steps: List[AgentStep] = []
    final_plan: Dict[str, Any] = {}

    for loop_num in range(1, MAX_LOOPS + 1):
        yield ("loop_start", {"loop": loop_num, "max_loops": MAX_LOOPS, "feedback": feedback})

        # ── PLAN ───────────────────────────────────────────────────────────
        yield ("plan", {"message": f"Generating plan (attempt {loop_num})..."})
        try:
            plan = planner.plan(task, context, memory_hints, feedback)
            final_plan = plan
            yield ("plan_ready", {
                "plan": plan,
                "steps_count": len(plan.get("steps", [])),
                "workflow_type": plan.get("workflow_type"),
                "risk_level": plan.get("risk_level"),
                "message": f"Plan ready — {len(plan.get('steps', []))} steps",
            })
        except Exception as e:
            yield ("error", {"message": f"Planning failed: {e}"})
            return
        await asyncio.sleep(0.3)

        # ── EXECUTE ────────────────────────────────────────────────────────
        yield ("execute", {"message": "Executing plan steps..."})
        completed_steps: List[AgentStep] = []
        try:
            for step_cfg in plan.get("steps", []):
                step = AgentStep(
                    step_number=step_cfg.get("step_number", len(completed_steps) + 1),
                    agent=step_cfg.get("agent", "executor"),
                    tool=step_cfg.get("tool", ""),
                    action=step_cfg.get("action", "execute"),
                    input_data={"parameters": step_cfg.get("parameters", {})},
                )
                yield ("step_start", {
                    "step": step.step_number,
                    "tool": step.tool,
                    "action": step.action,
                    "description": step_cfg.get("description", step.action),
                })
                await asyncio.sleep(0.3)
                step = await executor.execute_step(step)
                completed_steps.append(step)
                yield ("step_done", {
                    "step": step.step_number,
                    "status": step.status,
                    "output": step.output_data,
                    "error": step.error,
                    "duration_ms": step.duration_ms,
                })
                await asyncio.sleep(0.15)
        except Exception as e:
            yield ("error", {"message": f"Execution error: {e}"})
            return

        final_steps = completed_steps

        # ── REVIEW ─────────────────────────────────────────────────────────
        yield ("review", {"message": "Reviewing results..."})
        try:
            review = reviewer.review(task, plan, completed_steps)
            final_review = review
            passed = review.get("passed", False)
            yield ("review_done", {
                "passed": passed,
                "confidence": review.get("confidence", 0),
                "summary": review.get("summary", ""),
                "issues": review.get("issues", []),
                "recommendations": review.get("recommendations", []),
            })
        except Exception as e:
            yield ("review_done", {"passed": False, "summary": f"Review error: {e}"})
            review = {"passed": False, "recommendations": ["Retry"]}
            passed = False

        # ── UPDATE ─────────────────────────────────────────────────────────
        if passed:
            yield ("update", {"action": "pass", "message": f"Quality check passed on loop {loop_num} ✓"})
            _store_memory(task, plan, review)
            mem_update = review.get("memory_update", {})
            if mem_update.get("store", True):
                yield ("memory_stored", {
                    "category": mem_update.get("category", plan.get("workflow_type", "general")),
                    "message": "Solution stored in knowledge base for future reference",
                })
            break
        else:
            recs = review.get("recommendations", [])
            issues = review.get("issues", [])
            feedback = "; ".join(recs + issues) or "Improve plan and retry"
            if loop_num < MAX_LOOPS:
                yield ("update", {
                    "action": "retry",
                    "loop": loop_num,
                    "feedback": feedback,
                    "message": f"Retrying with feedback: {feedback[:80]}...",
                })
                await asyncio.sleep(0.5)
            else:
                yield ("update", {
                    "action": "max_loops",
                    "message": f"Max loops reached — delivering best result",
                })

    # ── COMPLETE ───────────────────────────────────────────────────────────
    yield ("complete", {
        "workflow_id": workflow_id,
        "passed": final_review.get("passed", False),
        "loops_used": loop_num,
        "summary": final_review.get("summary", ""),
        "next_actions": final_review.get("next_actions", []),
    })
