"""
AutoOps AI — Reviewer Agent
=============================
Reviews the workflow execution and provides a quality assessment.

Hybrid mode:
  - If ANTHROPIC_API_KEY is set  → uses real Claude API for intelligent review
  - If not set                   → falls back to rule-based mock reviewer
    (checks step completion rates and returns structured feedback)
"""

import json
import os
from typing import Any, Dict, List

from app.config.settings import settings
from app.models.workflow_model import AgentStep
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
# Mock reviewer — used when no API key is available
# ---------------------------------------------------------------------------

def _mock_review(
    task: str,
    plan: Dict[str, Any],
    steps: List[AgentStep],
) -> Dict[str, Any]:
    """Rule-based review based on step completion rates."""
    completed = sum(1 for s in steps if s.status == "completed")
    failed    = sum(1 for s in steps if s.status == "failed")
    total     = len(steps)

    pass_rate = completed / total if total else 0
    passed    = pass_rate >= 0.8  # pass if 80%+ steps succeeded
    confidence = round(pass_rate * 0.9, 2)  # slight discount for mock

    issues = []
    recommendations = []

    if failed:
        failed_names = [
            f"step {s.step_number} ({s.tool}.{s.action})"
            for s in steps if s.status == "failed"
        ]
        issues.append(f"Failed steps: {', '.join(failed_names)}")
        recommendations.append("Retry failed steps with corrected parameters")

    if pass_rate < 0.5:
        recommendations.append("Review tool configurations and retry the workflow")

    return {
        "passed": passed,
        "confidence": confidence,
        "summary": (
            f"[MOCK REVIEW] {completed}/{total} steps completed successfully."
            + (" Workflow passed." if passed else " Workflow needs retry.")
        ),
        "completed_steps": completed,
        "failed_steps": failed,
        "issues": issues,
        "recommendations": recommendations,
        "next_actions": ["Monitor execution logs"] if passed else ["Retry workflow"],
        "memory_update": {
            "store": passed,
            "category": plan.get("workflow_type", "general"),
            "lesson": f"[MOCK] Task '{task[:60]}' completed with {completed}/{total} steps",
        },
        "mode": "mock",
    }


# ---------------------------------------------------------------------------
# ReviewerAgent — hybrid: real LLM or mock
# ---------------------------------------------------------------------------

class ReviewerAgent:
    def __init__(self):
        api_key = settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self._use_mock = False
            logger.info("[ReviewerAgent] Initialized with real Claude API")
        else:
            self.client = None
            self._use_mock = True
            logger.warning(
                "[ReviewerAgent] No ANTHROPIC_API_KEY found — running in MOCK mode. "
                "Set ANTHROPIC_API_KEY in your .env to enable real LLM review."
            )

    def review(
        self,
        task: str,
        plan: Dict[str, Any],
        steps: List[AgentStep],
    ) -> Dict[str, Any]:
        logger.info(f"[ReviewerAgent] Reviewing {len(steps)} steps")

        # ── MOCK PATH ──────────────────────────────────────────────────────
        if self._use_mock:
            logger.info("[ReviewerAgent] Using mock reviewer (no API key)")
            review = _mock_review(task, plan, steps)
            logger.info(
                f"[ReviewerAgent] Mock review: passed={review['passed']}, "
                f"confidence={review['confidence']}"
            )
            return review

        # ── REAL LLM PATH ──────────────────────────────────────────────────
        steps_summary = [
            {
                "step": s.step_number,
                "tool": s.tool,
                "action": s.action,
                "status": s.status,
                "output": s.output_data,
                "error": s.error,
                "duration_ms": s.duration_ms,
            }
            for s in steps
        ]

        completed = sum(1 for s in steps if s.status == "completed")
        failed    = sum(1 for s in steps if s.status == "failed")

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=800,
            system=REVIEWER_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Original task: {task}\n\n"
                    f"Plan: {plan.get('task_summary', '')} | Risk: {plan.get('risk_level', 'unknown')}\n\n"
                    f"Steps: {completed} completed, {failed} failed out of {len(steps)} total\n\n"
                    f"Execution results:\n{json.dumps(steps_summary, indent=2, default=str)}"
                ),
            }],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        review = json.loads(raw)
        logger.info(
            f"[ReviewerAgent] Review: passed={review.get('passed')}, "
            f"confidence={review.get('confidence')}"
        )
        return review
