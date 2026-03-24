"""
AutoOps AI — Planner Agent
===========================
Analyses the incoming task and generates a structured JSON execution plan.

On retry loops, the planner receives specific feedback from the reviewer
(e.g. "step 2 failed to verify transaction before initiating refund") and
incorporates that into a revised plan — this is what makes self-correction
DIRECTED rather than just a blind retry.

Hybrid mode:
  - If ANTHROPIC_API_KEY is set  → uses real Claude API
  - If not set                   → falls back to rule-based mock planner
    (perfect for local dev, CI, or demo environments)
"""

import json
import os
from typing import Any, Dict, List, Optional

from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

PLANNER_SYSTEM = """You are the Planner Agent in AutoOps AI — an autonomous operations management system.
Analyse the user's task and produce a precise execution plan.

Available tools:
- payment_tool     → process_payment, refund, get_transaction, check_duplicate
- database_tool    → query, update, insert
- notification_tool → send_email, send_slack, notify_team
- ticket_tool      → create_ticket, update_ticket
- report_tool      → generate_report
- invoice_tool     → generate_invoice, send_invoice
- knowledge_tool   → search, store
- resume_tool      → screen_resumes
- delivery_tool    → check_delivery_status, create_investigation

If feedback from a previous attempt is provided, revise the plan to address
those specific issues before repeating the same steps.

Respond ONLY with valid JSON (no markdown fences):
{
  "task_summary": "Brief description",
  "workflow_type": "payment|delivery|invoice|report|resume|incident|general",
  "steps": [
    {
      "step_number": 1,
      "agent": "executor",
      "tool": "tool_name",
      "action": "method_name",
      "description": "Human-readable description of this step",
      "parameters": {},
      "depends_on": []
    }
  ],
  "estimated_duration_seconds": 30,
  "risk_level": "low|medium|high",
  "retry_reason": "What was wrong in the previous attempt (empty on first run)"
}"""


# ---------------------------------------------------------------------------
# Mock planner — used when no API key is available
# ---------------------------------------------------------------------------

def _infer_workflow_type(task: str) -> str:
    task_lower = task.lower()
    if any(w in task_lower for w in ["pay", "refund", "invoice", "charge", "transaction"]):
        return "payment"
    if any(w in task_lower for w in ["deliver", "shipment", "track", "order"]):
        return "delivery"
    if any(w in task_lower for w in ["report", "summary", "analytics"]):
        return "report"
    if any(w in task_lower for w in ["resume", "cv", "candidate", "hire"]):
        return "resume"
    if any(w in task_lower for w in ["ticket", "issue", "incident", "bug"]):
        return "incident"
    return "general"


def _mock_plan(task: str, feedback: str = "") -> Dict[str, Any]:
    """Rule-based fallback plan when no API key is configured.

    All parameter keys are aligned with the actual tool method signatures
    in all_tools.py so the executor never gets a TypeError.
    """
    workflow_type = _infer_workflow_type(task)

    # ── Per-workflow step definitions (parameters match tool signatures) ──
    workflow_steps: Dict[str, list] = {
        "payment": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "payment_tool",
                "action": "get_transaction",
                # get_transaction(transaction_id: str)
                "description": f"[MOCK] Fetch transaction details for: {task[:60]}",
                "parameters": {"transaction_id": "TXN-MOCK-001"},
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                # notify_team(team: str, message: str, urgency: str = "normal")
                "description": "[MOCK] Notify finance team of payment result",
                "parameters": {
                    "team": "finance",
                    "message": f"Payment task completed: {task[:60]}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ],
        "delivery": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "delivery_tool",
                "action": "check_delivery_status",
                # check_delivery_status(order_id: str)
                "description": f"[MOCK] Check delivery status for: {task[:60]}",
                "parameters": {"order_id": "ORD-MOCK-001"},
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                "description": "[MOCK] Notify logistics team of delivery result",
                "parameters": {
                    "team": "logistics",
                    "message": f"Delivery task completed: {task[:60]}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ],
        "report": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "report_tool",
                "action": "generate_report",
                # generate_report(report_type: str, period: str = "weekly", format: str = "pdf")
                "description": f"[MOCK] Generate report for: {task[:60]}",
                "parameters": {
                    "report_type": "operations",
                    "period": "weekly",
                    "format": "pdf",
                },
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                "description": "[MOCK] Notify management of report",
                "parameters": {
                    "team": "management",
                    "message": f"Report ready: {task[:60]}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ],
        "resume": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "resume_tool",
                "action": "screen_resumes",
                # screen_resumes(job_title: str, requirements: List[str] = None, resume_count: int = 15)
                "description": f"[MOCK] Screen resumes for: {task[:60]}",
                "parameters": {
                    "job_title": task[:80],
                    "requirements": ["Python", "3+ years experience"],
                    "resume_count": 15,
                },
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                "description": "[MOCK] Notify HR team of screening results",
                "parameters": {
                    "team": "hr",
                    "message": f"Resume screening complete: {task[:60]}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ],
        "incident": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "ticket_tool",
                "action": "create_ticket",
                # create_ticket(title: str, description: str, priority: str = "medium", ...)
                "description": f"[MOCK] Create incident ticket for: {task[:60]}",
                "parameters": {
                    "title": task[:80],
                    "description": f"Auto-generated ticket for: {task}",
                    "priority": "medium",
                    "category": "incident",
                },
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                "description": "[MOCK] Notify ops team of new incident",
                "parameters": {
                    "team": "ops",
                    "message": f"Incident ticket created: {task[:60]}",
                    "urgency": "high",
                },
                "depends_on": [1],
            },
        ],
        "general": [
            {
                "step_number": 1,
                "agent": "executor",
                "tool": "knowledge_tool",
                "action": "search",
                # search(query: str, top_k: int = 3)
                "description": f"[MOCK] Search knowledge base for: {task[:60]}",
                "parameters": {
                    "query": task,
                    "top_k": 3,
                },
                "depends_on": [],
            },
            {
                "step_number": 2,
                "agent": "executor",
                "tool": "notification_tool",
                "action": "notify_team",
                "description": "[MOCK] Notify team of task completion",
                "parameters": {
                    "team": "ops",
                    "message": f"Task completed: {task[:60]}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ],
    }

    steps = workflow_steps.get(workflow_type, workflow_steps["general"])

    return {
        "task_summary": f"[MOCK PLAN] {task[:80]}",
        "workflow_type": workflow_type,
        "steps": steps,
        "estimated_duration_seconds": 10,
        "risk_level": "low",
        "retry_reason": feedback or "",
        "mode": "mock",
    }


# ---------------------------------------------------------------------------
# PlannerAgent — hybrid: real LLM or mock
# ---------------------------------------------------------------------------

class PlannerAgent:
    def __init__(self):
        api_key = settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
        if api_key:
            import anthropic
            self.client = anthropic.Anthropic(api_key=api_key)
            self._use_mock = False
            logger.info("[PlannerAgent] Initialized with real Claude API")
        else:
            self.client = None
            self._use_mock = True
            logger.warning(
                "[PlannerAgent] No ANTHROPIC_API_KEY found — running in MOCK mode. "
                "Set ANTHROPIC_API_KEY in your .env to enable real LLM planning."
            )

    def plan(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
        memory_hints: Optional[List[Dict]] = None,
        feedback: str = "",
    ) -> Dict[str, Any]:
        """
        Generate an execution plan for the given task.

        Args:
            task:         The user's operational request.
            context:      Optional extra context (customer ID, order ID, etc.).
            memory_hints: Similar resolved workflows from memory store.
            feedback:     Reviewer feedback from previous attempt (empty on loop 1).

        Returns:
            dict with keys: task_summary, workflow_type, steps, risk_level, etc.
        """
        logger.info(f"[PlannerAgent] Planning task: {task[:80]}")
        if feedback:
            logger.info(f"[PlannerAgent] Incorporating feedback: {feedback[:100]}")

        # ── MOCK PATH ──────────────────────────────────────────────────────
        if self._use_mock:
            logger.info("[PlannerAgent] Using mock planner (no API key)")
            plan = _mock_plan(task, feedback)
            logger.info(
                f"[PlannerAgent] Mock plan ready — {len(plan['steps'])} steps | "
                f"type={plan['workflow_type']}"
            )
            return plan

        # ── REAL LLM PATH ──────────────────────────────────────────────────
        user_content = f"Task: {task}"
        if context:
            user_content += f"\n\nContext:\n{json.dumps(context, indent=2)}"
        if memory_hints:
            user_content += "\n\nSimilar past workflows (use as reference):\n"
            user_content += "\n".join(
                f"- {h.get('document', '')[:200]}" for h in memory_hints[:3]
            )
        if feedback:
            user_content += (
                f"\n\n⚠️  FEEDBACK FROM PREVIOUS ATTEMPT (must address these issues):\n"
                f"{feedback}\n\n"
                f"Revise the plan to fix the above before retrying the same steps."
            )

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1500,
            system=PLANNER_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        plan = json.loads(raw)
        step_count = len(plan.get("steps", []))
        logger.info(
            f"[PlannerAgent] Plan ready — {step_count} steps | "
            f"type={plan.get('workflow_type')} | risk={plan.get('risk_level')}"
        )
        return plan
