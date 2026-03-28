"""
AutoOps AI — Reviewer Agent
=============================
Reviews workflow execution and drives intelligent self-correction.

Hybrid mode:
  - ANTHROPIC_API_KEY set  → real Claude review
  - Not set               → smart rule-based reviewer (see below)

Smart mock reviewer does MORE than count pass/fail:
  1. Inspects the actual error message on each failed step
  2. Classifies the failure pattern (param mismatch / not found / timeout / logic)
  3. Generates TARGETED feedback that the planner can act on
  4. Adjusts confidence based on output quality, not just pass/fail count
  5. Checks output completeness (e.g. refund without transaction lookup = incomplete)
"""

import json
import os
import re
from typing import Any, Dict, List

from app.config.settings import settings
from app.llm_client import llm_complete, get_llm_client
from app.models.workflow_model import AgentStep
from app.tools.all_tools import PaymentTool
from app.utils.logger import get_logger

logger = get_logger(__name__)

REVIEWER_SYSTEM = """You are the Reviewer Agent in AutoOps AI.
Review the workflow execution and provide a quality assessment.

Respond ONLY with valid JSON (no markdown fences):
{
  "passed": true,
  "confidence": 0.95,
  "summary": "Concise summary of outcome",
  "completed_steps": 4,
  "failed_steps": 0,
  "issues": [],
  "recommendations": [],
  "next_actions": [],
  "memory_update": {
    "store": true,
    "category": "category_name",
    "lesson": "What was learned from this workflow"
  }
}"""


# ---------------------------------------------------------------------------
# Failure pattern classifier
# ---------------------------------------------------------------------------

class FailurePattern:
    PARAM_MISMATCH  = "param_mismatch"
    NOT_FOUND       = "not_found"
    LOGIC_ERROR     = "logic_error"
    INCOMPLETE      = "incomplete_workflow"
    TOOL_ERROR      = "tool_error"
    UNKNOWN         = "unknown"


def _classify_failure(error: str) -> str:
    if not error:
        return FailurePattern.UNKNOWN
    e = error.lower()
    if any(k in e for k in ["unexpected keyword", "missing.*argument", "got an unexpected",
                              "argument", "positional"]):
        return FailurePattern.PARAM_MISMATCH
    if any(k in e for k in ["not found", "no such", "does not exist", "not_found", "404"]):
        return FailurePattern.NOT_FOUND
    if any(k in e for k in ["attribute", "none", "noneType", "key error", "keyerror"]):
        return FailurePattern.LOGIC_ERROR
    if any(k in e for k in ["timeout", "connection", "refused", "unreachable"]):
        return FailurePattern.TOOL_ERROR
    return FailurePattern.UNKNOWN


def _targeted_recommendation(step: AgentStep, pattern: str) -> str:
    """Generate a specific, actionable recommendation for each failure."""
    tool_action = f"{step.tool}.{step.action}"
    params = step.input_data.get("parameters", {})

    if pattern == FailurePattern.PARAM_MISMATCH:
        return (
            f"Fix parameter names for {tool_action}. "
            f"Current params: {list(params.keys())}. "
            f"Check the tool signature and rename keys accordingly."
        )
    if pattern == FailurePattern.NOT_FOUND:
        id_val = next((v for v in params.values() if isinstance(v, str)
                       and any(p in v for p in ["TXN-", "ORD-", "CUST-", "INV-"])), None)
        return (
            f"{tool_action}: resource not found. "
            + (f"Verify that {id_val} exists before this step. "
               f"Add a lookup/verify step before step {step.step_number}."
               if id_val else "Add a data-fetch step first.")
        )
    if pattern == FailurePattern.LOGIC_ERROR:
        return (
            f"{tool_action}: logic error — a previous step likely returned None or unexpected type. "
            f"Check that step {max(step.step_number - 1, 1)} output is not empty before proceeding."
        )
    if pattern == FailurePattern.TOOL_ERROR:
        return (
            f"{tool_action}: connectivity issue. Retry this step with exponential backoff, "
            f"or switch to fallback tool if available."
        )
    return f"Investigate {tool_action} failure: {step.error or 'unknown error'}. Retry with corrected inputs."


# ---------------------------------------------------------------------------
# Output quality scorer
# ---------------------------------------------------------------------------

def _score_output_quality(step: AgentStep) -> float:
    """
    Returns a 0–1 quality score for a completed step's output.
    A step can succeed technically but return poor/empty output.
    """
    if step.status != "completed" or not step.output_data:
        return 0.0
    out = step.output_data

    # Failure signals inside "successful" outputs
    if out.get("status") in ("not_found", "error", "failed"):
        return 0.3
    if out.get("total_found", 1) == 0:
        return 0.4   # knowledge search returned nothing
    if out.get("shortlisted_count", 1) == 0 and step.action == "screen_resumes":
        return 0.5   # screening found no candidates
    if out.get("duplicate_found") is False and step.action == "check_duplicate":
        return 0.8   # not a failure, just no duplicate

    return 1.0


# ---------------------------------------------------------------------------
# Workflow completeness checker
# ---------------------------------------------------------------------------

# What every workflow type SHOULD cover (minimum required tool types)
_REQUIRED_COVERAGE: Dict[str, List[str]] = {
    "payment_failure_remediation": ["payment_tool", "ticket_tool", "notification_tool"],
}


def _check_completeness(workflow_type: str, steps: List[AgentStep]) -> List[str]:
    """Return a list of missing coverage issues."""
    completed_tools = {s.tool for s in steps if s.status == "completed"}
    required        = _REQUIRED_COVERAGE.get(workflow_type, [])
    missing         = [t for t in required if t not in completed_tools]
    issues = []
    if missing:
        issues.append(
            f"Workflow type '{workflow_type}' requires {missing} but those tools "
            f"did not complete successfully."
        )
    return issues


# ---------------------------------------------------------------------------
# Deterministic post-condition checks
# ---------------------------------------------------------------------------

def _check_post_conditions(steps: List[AgentStep]) -> List[str]:
    """
    Verify deterministic invariants after key steps.
    Returns list of failed checks (empty = all passed).
    """
    issues = []
    
    # Check refund was processed
    refund_steps = [s for s in steps if s.tool == "payment_tool" and s.action == "refund"]
    payment_tool = PaymentTool()
    for step in refund_steps:
        if step.status == "completed":
            txn_id = step.input_data.get("parameters", {}).get("transaction_id")
            refund_id = step.output_data.get("refund_id") if isinstance(step.output_data, dict) else None
            if txn_id and refund_id:
                verified = payment_tool.verify_refund_status(txn_id, refund_id)
                if not verified:
                    issues.append(
                        f"Refund {refund_id} for transaction {txn_id} did not verify successfully"
                    )
            elif txn_id:
                if "refunded" not in str(step.output_data).lower():
                    issues.append(f"Refund for {txn_id} not confirmed in output")
    
    # Check ticket was created
    ticket_steps = [s for s in steps if s.tool == "ticket_tool" and s.action == "create_ticket"]
    for step in ticket_steps:
        if step.status == "completed":
            title = step.input_data.get("parameters", {}).get("title")
            if title and "ticket_id" not in str(step.output_data):
                issues.append(f"Ticket creation for '{title}' did not return ticket_id")
    
    # Check notification was sent
    notify_steps = [s for s in steps if s.tool == "notification_tool"]
    for step in notify_steps:
        if step.status == "completed":
            if "sent" not in str(step.output_data).lower() and "notified" not in str(step.output_data).lower():
                issues.append(f"Notification step {step.step_number} output does not confirm delivery")
    
    return issues


# ---------------------------------------------------------------------------
# Smart mock reviewer
# ---------------------------------------------------------------------------

def _mock_review(
    task: str,
    plan: Dict[str, Any],
    steps: List[AgentStep],
) -> Dict[str, Any]:
    """
    Intelligent rule-based reviewer.

    Goes beyond pass/fail counts:
      - Classifies each failure with a pattern
      - Generates targeted per-step recommendations
      - Scores output quality (not just completion status)
      - Checks workflow completeness against required tool coverage
      - Produces actionable feedback for the retry loop
    """
    if not steps:
        return {
            "passed": False, "confidence": 0.0,
            "summary": "No steps were executed.",
            "completed_steps": 0, "failed_steps": 0,
            "issues": ["No steps executed"],
            "recommendations": ["Verify plan generation produced valid steps"],
            "next_actions": ["Re-plan"],
            "memory_update": {"store": False, "category": "general", "lesson": ""},
            "mode": "mock",
        }

    completed = [s for s in steps if s.status == "completed"]
    failed    = [s for s in steps if s.status == "failed"]
    total     = len(steps)

    # ── Per-step analysis ─────────────────────────────────────────────────
    issues: List[str] = []
    recommendations: List[str] = []
    failure_patterns: Dict[str, int] = {}

    for step in failed:
        pattern = _classify_failure(step.error or "")
        failure_patterns[pattern] = failure_patterns.get(pattern, 0) + 1
        rec = _targeted_recommendation(step, pattern)
        issues.append(
            f"Step {step.step_number} ({step.tool}.{step.action}) failed "
            f"[{pattern}]: {(step.error or '')[:100]}"
        )
        recommendations.append(rec)
        logger.info(f"[ReviewerAgent] Step {step.step_number} failure classified as {pattern}")

    # ── Output quality check ──────────────────────────────────────────────
    quality_scores = [_score_output_quality(s) for s in completed]
    avg_quality = (sum(quality_scores) / len(quality_scores)) if quality_scores else 0.0

    poor_quality = [
        s for s, q in zip(completed, quality_scores) if q < 0.6
    ]
    for step in poor_quality:
        issues.append(
            f"Step {step.step_number} ({step.tool}.{step.action}) completed but "
            f"output quality is low: status={step.output_data.get('status')}"
        )
        recommendations.append(
            f"Improve {step.tool}.{step.action}: output indicates a soft failure. "
            f"Verify input parameters produce meaningful results."
        )

    # ── Completeness check ────────────────────────────────────────────────
    workflow_type = plan.get("workflow_type", "general")
    completeness_issues = _check_completeness(workflow_type, steps)
    issues.extend(completeness_issues)
    if completeness_issues:
        recommendations.append(
            f"Add missing tool steps to satisfy {workflow_type} workflow requirements."
        )

    # ── Deterministic post-condition checks ──────────────────────────────
    post_condition_issues = _check_post_conditions(steps)
    issues.extend(post_condition_issues)
    if post_condition_issues:
        recommendations.append("Fix post-condition failures: verify API responses confirm actions were completed")

    # ── Scoring ───────────────────────────────────────────────────────────
    completion_rate = len(completed) / total if total else 0
    quality_weight  = avg_quality * 0.3
    completion_weight = completion_rate * 0.5
    completeness_weight = (0 if completeness_issues else 0.2)
    confidence = round(completion_weight + quality_weight + completeness_weight, 2)

    # Any poor-quality step (score < 0.6) is a hard fail signal
    any_poor_quality = any(q < 0.6 for q in quality_scores)

    passed = (
        completion_rate >= 0.8
        and avg_quality > 0.7          # strictly above threshold
        and not completeness_issues
        and not any_poor_quality       # no individual step with poor output
    )

    # ── Summary ───────────────────────────────────────────────────────────
    dominant_pattern = max(failure_patterns, key=failure_patterns.get) \
                       if failure_patterns else None
    summary_parts = [
        f"{len(completed)}/{total} steps completed",
        f"quality={avg_quality:.0%}",
    ]
    if dominant_pattern:
        summary_parts.append(f"dominant failure: {dominant_pattern}")
    if completeness_issues:
        summary_parts.append("workflow incomplete")
    summary = (
        f"[REVIEW] {' | '.join(summary_parts)}. "
        + ("Workflow passed ✓" if passed else "Needs retry ✗")
    )

    logger.info(
        f"[ReviewerAgent] passed={passed} confidence={confidence} "
        f"completion={completion_rate:.0%} quality={avg_quality:.0%}"
    )

    return {
        "passed":           passed,
        "confidence":       confidence,
        "summary":          summary,
        "completed_steps":  len(completed),
        "failed_steps":     len(failed),
        "issues":           issues,
        "recommendations":  recommendations,
        "failure_patterns": failure_patterns,
        "next_actions":     (
            ["Monitor workflow logs"] if passed
            else ["Retry with targeted feedback", "Review tool parameters"]
        ),
        "memory_update": {
            "store":    passed,
            "category": workflow_type,
            "lesson":   (
                f"Successfully completed {workflow_type} workflow: {task[:80]}"
                if passed else
                f"Failed {workflow_type} workflow. Issues: {'; '.join(issues[:2])}"
            ),
        },
        "mode": "mock",
    }


# ---------------------------------------------------------------------------
# ReviewerAgent — hybrid: real LLM or smart mock
# ---------------------------------------------------------------------------

class ReviewerAgent:
    def __init__(self):
        client = get_llm_client()
        self._use_mock = (client is None)
        if not self._use_mock:
            logger.info(f"[ReviewerAgent] Initialized with {client.provider} LLM")
        else:
            logger.warning(
                "[ReviewerAgent] No LLM API key found — running smart mock reviewer. "
                "Set ANTHROPIC_API_KEY, GROQ_API_KEY, or HF_API_KEY in .env."
            )

    def review(
        self,
        task: str,
        plan: Dict[str, Any],
        steps: List[AgentStep],
    ) -> Dict[str, Any]:
        logger.info(f"[ReviewerAgent] Reviewing {len(steps)} steps for: {task[:60]}")

        if self._use_mock:
            result = _mock_review(task, plan, steps)
            return result

        # ── Real LLM review ───────────────────────────────────────────────
        steps_summary = [
            {
                "step": s.step_number, "tool": s.tool, "action": s.action,
                "status": s.status, "output": s.output_data,
                "error": s.error, "duration_ms": s.duration_ms,
            }
            for s in steps
        ]
        completed = sum(1 for s in steps if s.status == "completed")
        failed    = sum(1 for s in steps if s.status == "failed")

        user_msg = (
            f"Original task: {task}\n\n"
            f"Plan: {plan.get('task_summary', '')} | Risk: {plan.get('risk_level','unknown')}\n\n"
            f"Steps: {completed} completed, {failed} failed out of {len(steps)} total\n\n"
            f"Execution results:\n{json.dumps(steps_summary, indent=2, default=str)}"
        )
        raw = llm_complete(REVIEWER_SYSTEM, user_msg, max_tokens=800)
        if raw is None:
            logger.warning("[ReviewerAgent] LLM returned None — falling back to mock review")
            return _mock_review(task, plan, steps)
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        review = json.loads(raw)
        logger.info(
            f"[ReviewerAgent] LLM review: passed={review.get('passed')}, "
            f"confidence={review.get('confidence')}"
        )
        return review
