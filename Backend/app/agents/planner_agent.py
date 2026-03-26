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
from app.llm_client import llm_complete, get_llm_client
from app.utils.logger import get_logger

logger = get_logger(__name__)

PLANNER_SYSTEM = """You are the Planner Agent in AutoOps AI — an autonomous campus payment failure remediation system for the Bursar's Office.
Analyse the user's task and produce a precise execution plan for payment failure remediation.

Available tools:
- payment_tool     → process_payment, refund, get_transaction, check_duplicate
- database_tool    → query, update, insert (student records, payments)
- notification_tool → send_email, send_slack, notify_team
- ticket_tool      → create_ticket, update_ticket (ITSM for remediation tracking)

Focus on campus payment failure scenarios: failed tuition payments, chargebacks, duplicate charges, etc.
If feedback from a previous attempt is provided, revise the plan to address those specific issues.

Respond ONLY with valid JSON (no markdown fences):
{
  "task_summary": "Brief description",
  "workflow_type": "payment_failure_remediation",
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
# Task-aware mock planner — used when no API key is available
# ---------------------------------------------------------------------------

# ── Signal registry ─────────────────────────────────────────────────────────
# Each entry: (workflow_type, keywords, sub_type_hints)
# Sub-type hints let us pick the right action within a workflow
# (e.g. "refund" vs "duplicate charge" are both payment but need different steps)

_WORKFLOW_SIGNALS: List[tuple] = [
    # (workflow_type,  keyword list)
    ("payment_failure_remediation", ["payment failure", "tuition payment failed", "failed payment", "chargeback", "refund", "duplicate charge", "payment error", "bursar", "tuition", "student payment"]),
]


def _infer_workflow_type(task: str) -> str:
    """Always return payment_failure_remediation for campus focus."""
    return "payment_failure_remediation"


def _extract_context(task: str) -> Dict[str, Any]:
    """
    Pull structured values from free-text task descriptions.
    E.g. "refund order ORD-1234 for customer CUST-99" → {order_id, customer_id}
    """
    import re
    ctx: Dict[str, Any] = {}

    # Order / transaction / ticket / invoice IDs
    for pattern, key in [
        (r"\b(ORD-[\w]+)\b",  "order_id"),
        (r"\b(TXN-[\w]+)\b",  "transaction_id"),
        (r"\b(INV-[\w]+)\b",  "invoice_id"),
        (r"\b(OPS-[\d]+)\b",  "ticket_id"),
        (r"\b(CUST-[\w]+)\b", "customer_id"),
    ]:
        match = re.search(pattern, task, re.IGNORECASE)
        if match:
            ctx[key] = match.group(1).upper()

    # Monetary amounts  e.g. "$499" or "499.99 USD"
    amount_match = re.search(r"\$?([\d,]+\.?\d*)\s*(?:USD|INR|EUR)?", task)
    if amount_match:
        try:
            ctx["amount"] = float(amount_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Priority signals
    if any(w in task.lower() for w in ["urgent", "asap", "critical", "p1"]):
        ctx["priority"] = "high"
    elif any(w in task.lower() for w in ["low priority", "whenever", "no rush"]):
        ctx["priority"] = "low"
    else:
        ctx["priority"] = "medium"

    return ctx


# ── DB-aware ID resolvers ────────────────────────────────────────────────────
# Each resolver tries to find a real ID from SQLite before falling back.
# This prevents MOCK IDs from reaching tools that query the real database.

def _db_query(sql: str, params: tuple):
    """Run a single-row SQLite query against autoops.db. Returns the row or None."""
    try:
        import sqlite3 as _sqlite3
        from pathlib import Path as _Path
        db_path = _Path(__file__).parent.parent.parent / "autoops.db"
        conn = _sqlite3.connect(str(db_path))
        conn.row_factory = _sqlite3.Row
        row = conn.execute(sql, params).fetchone()
        conn.close()
        return row
    except Exception as e:
        logger.warning(f"[MockPlanner] DB lookup failed: {e}")
        return None


def _resolve_transaction_id(ctx: Dict[str, Any]) -> str:
    """Return a real txn_id from context, DB lookup by student, or sentinel."""
    if ctx.get("transaction_id"):
        return ctx["transaction_id"]
    student_id = ctx.get("student_id") or ctx.get("customer_id")  # backward compatibility
    if student_id:
        row = _db_query(
            "SELECT txn_id FROM transactions WHERE customer_id=? ORDER BY created_at DESC LIMIT 1",
            (student_id,)
        )
        if row:
            logger.info(f"[MockPlanner] Resolved transaction_id={row['txn_id']} for student={student_id}")
            return row["txn_id"]
    return "TXN-UNKNOWN"


def _resolve_order_id(ctx: Dict[str, Any]) -> str:
    """Return a real order_id from context, DB lookup by customer, or sentinel."""
    if ctx.get("order_id"):
        return ctx["order_id"]
    customer_id = ctx.get("customer_id")
    if customer_id:
        row = _db_query(
            "SELECT order_id FROM orders WHERE customer_id=? ORDER BY created_at DESC LIMIT 1",
            (customer_id,)
        )
        if row:
            logger.info(f"[MockPlanner] Resolved order_id={row['order_id']} for customer={customer_id}")
            return row["order_id"]
    return "ORD-UNKNOWN"


def _resolve_customer_id(ctx: Dict[str, Any]) -> str:
    """Return a real student_id from context, DB lookup by order/txn, or sentinel."""
    if ctx.get("student_id") or ctx.get("customer_id"):
        return ctx.get("student_id") or ctx["customer_id"]
    order_id = ctx.get("order_id")
    if order_id:
        row = _db_query(
            "SELECT customer_id FROM orders WHERE order_id=? LIMIT 1",
            (order_id,)
        )
        if row:
            logger.info(f"[MockPlanner] Resolved student_id={row['customer_id']} for order={order_id}")
            return row["customer_id"]
    txn_id = ctx.get("transaction_id")
    if txn_id:
        row = _db_query(
            "SELECT customer_id FROM transactions WHERE txn_id=? LIMIT 1",
            (txn_id,)
        )
        if row:
            logger.info(f"[MockPlanner] Resolved student_id={row['customer_id']} for txn={txn_id}")
            return row["customer_id"]
    return "STU-UNKNOWN"


def _resolve_customer_email(ctx: Dict[str, Any]) -> str:
    """Return a real student email from DB, or a safe default."""
    student_id = _resolve_customer_id(ctx)
    if not student_id.endswith("UNKNOWN"):
        row = _db_query(
            "SELECT email FROM customers WHERE customer_id=? LIMIT 1",
            (student_id,)
        )
        if row and row["email"]:
            logger.info(f"[MockPlanner] Resolved email={row['email']} for student={student_id}")
            return row["email"]
    return "student@university.edu"


def _mock_plan(task: str, feedback: str = "", memory_hints: list = None) -> Dict[str, Any]:
    """
    Intelligent rule-based planner used when no API key is configured.

    Detects workflow type via keyword scoring, extracts structured context
    (IDs, amounts, priority) from the task text, then builds a multi-step
    plan whose steps and parameters are specific to what the task actually
    asks for.  When memory_hints are provided, logs and potentially adjusts
    the priority/risk based on past failure patterns.
    """
    workflow_type = _infer_workflow_type(task)
    ctx           = _extract_context(task)

    # ── Apply memory hints to adjust planning context ────────────────────
    if memory_hints:
        for hint in memory_hints[:2]:
            doc = hint.get("document", "").lower()
            # If a past workflow of this type failed, bump risk
            if "failed" in doc and workflow_type in doc:
                logger.info(f"[MockPlanner] Memory hint suggests prior failure for '{workflow_type}' — bumping risk")
                ctx["_memory_risk_bump"] = True
            # If a past solution mentions a specific action sequence, log it
            if "solution:" in doc:
                logger.info(f"[MockPlanner] Memory hint solution: {doc[doc.find('solution:')+9:][:80]}")

    steps = _build_steps(workflow_type, task, ctx)

    # Risk: high if urgency extracted OR workflow is payment/incident
    risk = "high"   if ctx.get("priority") == "high" or workflow_type in ("incident", "refund", "duplicate") \
          else "medium" if workflow_type in ("payment", "delivery", "invoice") \
          else "low"

    logger.info(
        f"[MockPlanner] type={workflow_type} | steps={len(steps)} | "
        f"risk={risk} | ctx_keys={list(ctx.keys())}"
    )

    return {
        "task_summary":               f"[MOCK] {task[:80]}",
        "workflow_type":              workflow_type,
        "steps":                      steps,
        "estimated_duration_seconds": len(steps) * 5,
        "risk_level":                 risk,
        "retry_reason":               feedback or "",
        "mode":                       "mock",
        "extracted_context":          ctx,   # visible in logs / review
    }


def _build_steps(workflow_type: str, task: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a focused plan for campus payment failure remediation.
    """
    priority   = ctx.get("priority", "medium")
    urgency    = "high" if priority == "high" else "normal"
    short_task = task[:70]

    # ── PAYMENT FAILURE REMEDIATION ──────────────────────────────────────────
    if workflow_type == "payment_failure_remediation":
        txn_id = _resolve_transaction_id(ctx)
        amount = ctx.get("amount")
        student_id = _resolve_customer_id(ctx)  # Treat as student_id
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "payment_tool", "action": "get_transaction",
                "description": "Verify payment failure and transaction details",
                "parameters": {"transaction_id": txn_id},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "payment_tool", "action": "refund",
                "description": "Process refund for failed tuition payment",
                "parameters": {
                    "transaction_id": txn_id,
                    "amount": amount,
                    "reason": f"Payment failure remediation: {short_task}",
                },
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "ticket_tool", "action": "create_ticket",
                "description": "Create ITSM ticket for payment remediation tracking",
                "parameters": {
                    "title": f"Payment Failure Remediation - {txn_id}",
                    "description": f"Automated remediation for failed payment: {short_task}",
                    "priority": priority,
                    "assigned_to": "bursar_team",
                },
                "depends_on": [2],
            },
            {
                "step_number": 4, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify Bursar's Office of remediation completion",
                "parameters": {
                    "team": "bursar",
                    "message": f"Payment failure remediated for {txn_id}: refund processed, ticket created",
                    "urgency": urgency,
                },
                "depends_on": [3],
            },
        ]

    # Fallback for any other type (shouldn't happen)
    return [
        {
            "step_number": 1, "agent": "executor",
            "tool": "notification_tool", "action": "notify_team",
            "description": "Notify team of unrecognized task",
            "parameters": {
                "team": "ops",
                "message": f"Unrecognized task: {short_task}",
                "urgency": "high",
            },
            "depends_on": [],
        },
    ]


def _mock_plan(task: str, feedback: str = "", memory_hints: list = None) -> Dict[str, Any]:
    """
    Intelligent rule-based planner used when no API key is configured.

    Detects workflow type via keyword scoring, extracts structured context
    (IDs, amounts, priority) from the task text, then builds a multi-step
    plan whose steps and parameters are specific to what the task actually
    asks for.  When memory_hints are provided, logs and potentially adjusts
    the priority/risk based on past failure patterns.
    """
    workflow_type = _infer_workflow_type(task)
    ctx           = _extract_context(task)

    # ── Apply memory hints to adjust planning context ────────────────────
    if memory_hints:
        for hint in memory_hints[:2]:
            doc = hint.get("document", "").lower()
            # If a past workflow of this type failed, bump risk
            if "failed" in doc and workflow_type in doc:
                logger.info(f"[MockPlanner] Memory hint suggests prior failure for '{workflow_type}' — bumping risk")
                ctx["_memory_risk_bump"] = True
            # If a past solution mentions a specific action sequence, log it
            if "solution:" in doc:
                logger.info(f"[MockPlanner] Memory hint solution: {doc[doc.find('solution:')+9:][:80]}")

    steps = _build_steps(workflow_type, task, ctx)

    # Risk: high if urgency extracted OR workflow is payment/incident
    risk = "high"   if ctx.get("priority") == "high" or workflow_type in ("incident", "refund", "duplicate") \
          else "medium" if workflow_type in ("payment", "delivery", "invoice") \
          else "low"

    logger.info(
        f"[MockPlanner] type={workflow_type} | steps={len(steps)} | "
        f"risk={risk} | ctx_keys={list(ctx.keys())}"
    )

    return {
        "task_summary":               f"[MOCK] {task[:80]}",
        "workflow_type":              workflow_type,
        "steps":                      steps,
        "estimated_duration_seconds": len(steps) * 5,
        "risk_level":                 risk,
        "retry_reason":               feedback or "",
        "mode":                       "mock",
        "extracted_context":          ctx,   # visible in logs / review
    }


# ---------------------------------------------------------------------------
# PlannerAgent — hybrid: real LLM or mock
# ---------------------------------------------------------------------------

class PlannerAgent:
    def __init__(self):
        client = get_llm_client()
        self._use_mock = (client is None)
        if not self._use_mock:
            logger.info(f"[PlannerAgent] Initialized with {client.provider} LLM")
        else:
            logger.warning(
                "[PlannerAgent] No LLM API key found — running in MOCK mode. "
                "Set ANTHROPIC_API_KEY, GROQ_API_KEY, or HF_API_KEY in .env "
                "to enable real LLM planning."
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
            plan = _mock_plan(task, feedback, memory_hints or [])
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

        raw = llm_complete(PLANNER_SYSTEM, user_content, max_tokens=1500)
        if raw is None:
            logger.warning("[PlannerAgent] LLM returned None — falling back to mock")
            return _mock_plan(task, feedback)
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