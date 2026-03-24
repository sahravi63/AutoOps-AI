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
# Task-aware mock planner — used when no API key is available
# ---------------------------------------------------------------------------

# ── Signal registry ─────────────────────────────────────────────────────────
# Each entry: (workflow_type, keywords, sub_type_hints)
# Sub-type hints let us pick the right action within a workflow
# (e.g. "refund" vs "duplicate charge" are both payment but need different steps)

_WORKFLOW_SIGNALS: List[tuple] = [
    # (workflow_type,  keyword list)
    ("refund",        ["refund", "chargeback", "money back", "overcharged"]),
    ("duplicate",     ["duplicate", "charged twice", "double charge"]),
    ("payment",       ["pay", "payment", "transaction", "charge", "invoice", "billing"]),
    ("delivery",      ["deliver", "shipment", "track", "order", "shipping", "courier"]),
    ("report",        ["report", "summary", "analytics", "dashboard", "metrics", "kpi"]),
    ("resume",        ["resume", "cv", "candidate", "hire", "recruit", "screening", "job"]),
    ("incident",      ["incident", "outage", "down", "crash", "error", "bug", "issue", "ticket"]),
    ("database",      ["database", "db", "query", "table", "record", "data", "sql"]),
    ("email",         ["email", "send mail", "notify", "alert", "message"]),
    ("invoice",       ["invoice", "bill", "billing", "generate invoice", "send invoice"]),
]


def _infer_workflow_type(task: str) -> str:
    """Score the task against every signal group; return the highest-scoring type."""
    task_lower = task.lower()
    scores: Dict[str, int] = {}
    for workflow_type, keywords in _WORKFLOW_SIGNALS:
        score = sum(1 for kw in keywords if kw in task_lower)
        if score:
            scores[workflow_type] = scores.get(workflow_type, 0) + score
    if not scores:
        return "general"
    return max(scores, key=lambda k: scores[k])


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


def _build_steps(workflow_type: str, task: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return a task-specific, multi-step plan whose steps reflect what the task
    actually asks for — not just a generic 2-step template.
    """
    priority   = ctx.get("priority", "medium")
    urgency    = "high" if priority == "high" else "normal"
    short_task = task[:70]

    # ── REFUND ───────────────────────────────────────────────────────────────
    if workflow_type == "refund":
        txn_id = ctx.get("transaction_id", "TXN-MOCK-001")
        amount = ctx.get("amount")
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "payment_tool", "action": "get_transaction",
                "description": f"Fetch original transaction to verify refund eligibility",
                "parameters": {"transaction_id": txn_id},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "payment_tool", "action": "refund",
                "description": "Initiate refund for the transaction",
                "parameters": {
                    "transaction_id": txn_id,
                    "amount": amount,
                    "reason": f"Customer request: {short_task}",
                },
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify finance team of refund",
                "parameters": {
                    "team": "finance",
                    "message": f"Refund processed for {txn_id}: {short_task}",
                    "urgency": urgency,
                },
                "depends_on": [2],
            },
        ]

    # ── DUPLICATE CHARGE ─────────────────────────────────────────────────────
    if workflow_type == "duplicate":
        customer_id = ctx.get("customer_id", "CUST-MOCK-001")
        amount      = ctx.get("amount", 0.0)
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "payment_tool", "action": "check_duplicate",
                "description": "Detect duplicate charge for the customer",
                "parameters": {"customer_id": customer_id, "amount": amount},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "payment_tool", "action": "refund",
                "description": "Refund the duplicate transaction",
                "parameters": {
                    "transaction_id": ctx.get("transaction_id", "TXN-MOCK-DUP"),
                    "reason": "Duplicate charge detected",
                },
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "send_email",
                "description": "Email customer confirmation of duplicate refund",
                "parameters": {
                    "to": "customer@example.com",
                    "subject": "Duplicate Charge Refunded",
                    "body": f"We've refunded your duplicate charge. Task: {short_task}",
                },
                "depends_on": [2],
            },
        ]

    # ── PAYMENT (generic — check status / process) ────────────────────────────
    if workflow_type == "payment":
        txn_id = ctx.get("transaction_id", "TXN-MOCK-001")
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "payment_tool", "action": "get_transaction",
                "description": "Retrieve payment transaction details",
                "parameters": {"transaction_id": txn_id},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "database_tool", "action": "query",
                "description": "Cross-check transaction in orders database",
                "parameters": {"table": "transactions", "filters": {"txn_id": txn_id}, "limit": 1},
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify finance team of payment status",
                "parameters": {
                    "team": "finance",
                    "message": f"Payment review complete for {txn_id}: {short_task}",
                    "urgency": urgency,
                },
                "depends_on": [2],
            },
        ]

    # ── DELIVERY ─────────────────────────────────────────────────────────────
    if workflow_type == "delivery":
        order_id = ctx.get("order_id", "ORD-MOCK-001")
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "delivery_tool", "action": "check_delivery_status",
                "description": f"Check current delivery status for order {order_id}",
                "parameters": {"order_id": order_id},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "database_tool", "action": "query",
                "description": "Fetch order details from database",
                "parameters": {"table": "orders", "filters": {"order_id": order_id}, "limit": 1},
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "delivery_tool", "action": "create_investigation",
                "description": "Open delivery investigation if needed",
                "parameters": {
                    "order_id": order_id,
                    "issue": f"Customer query: {short_task}",
                },
                "depends_on": [2],
            },
            {
                "step_number": 4, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify logistics team of investigation",
                "parameters": {
                    "team": "logistics",
                    "message": f"Delivery investigation opened for {order_id}: {short_task}",
                    "urgency": urgency,
                },
                "depends_on": [3],
            },
        ]

    # ── REPORT ───────────────────────────────────────────────────────────────
    if workflow_type == "report":
        # Try to detect report type from task keywords
        task_lower = task.lower()
        if   "sales"   in task_lower: report_type = "sales"
        elif "hr"      in task_lower: report_type = "hr"
        elif "finance" in task_lower: report_type = "finance"
        else:                          report_type = "operations"

        period = "monthly" if "month" in task_lower else \
                 "daily"   if "day"   in task_lower or "today" in task_lower else "weekly"
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "database_tool", "action": "query",
                "description": f"Pull raw {report_type} data from database",
                "parameters": {"table": "orders", "filters": {}, "limit": 50},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "report_tool", "action": "generate_report",
                "description": f"Generate {period} {report_type} report",
                "parameters": {"report_type": report_type, "period": period, "format": "pdf"},
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Distribute report to management",
                "parameters": {
                    "team": "management",
                    "message": f"{period.title()} {report_type} report is ready: {short_task}",
                    "urgency": urgency,
                },
                "depends_on": [2],
            },
        ]

    # ── RESUME SCREENING ─────────────────────────────────────────────────────
    if workflow_type == "resume":
        import re
        # Try to extract job title from task — "hire a Python engineer" → "Python engineer"
        title_match = re.search(
            r"(?:hire|recruit|screen|find|looking for|need)\s+(?:a\s+)?(.+?)(?:\s+for|\s+with|\.|$)",
            task, re.IGNORECASE
        )
        job_title = title_match.group(1).strip() if title_match else task[:60]

        # Extract skills from task
        skill_keywords = ["python", "java", "react", "node", "aws", "docker",
                          "kubernetes", "ml", "ai", "fastapi", "django", "sql"]
        requirements = [kw.upper() if len(kw) <= 3 else kw.title()
                        for kw in skill_keywords if kw in task.lower()]
        if not requirements:
            requirements = ["Relevant experience", "Communication skills"]

        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "knowledge_tool", "action": "search",
                "description": f"Search knowledge base for {job_title} hiring criteria",
                "parameters": {"query": f"hiring criteria {job_title}", "top_k": 3},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "resume_tool", "action": "screen_resumes",
                "description": f"Screen resumes for {job_title}",
                "parameters": {
                    "job_title": job_title,
                    "requirements": requirements,
                    "resume_count": 20,
                },
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify HR team with shortlist",
                "parameters": {
                    "team": "hr",
                    "message": f"Resume screening done for '{job_title}': {short_task}",
                    "urgency": urgency,
                },
                "depends_on": [2],
            },
        ]

    # ── INCIDENT / BUG / OUTAGE ───────────────────────────────────────────────
    if workflow_type == "incident":
        task_lower = task.lower()
        category  = "outage"   if any(w in task_lower for w in ["down", "outage", "crash"]) else \
                    "security" if any(w in task_lower for w in ["breach", "hack", "security"]) else \
                    "bug"      if any(w in task_lower for w in ["bug", "error", "exception"]) else \
                    "incident"
        urgency_override = "high" if priority == "high" or category in ("outage", "security") \
                           else urgency
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "knowledge_tool", "action": "search",
                "description": "Search knowledge base for similar incidents and runbooks",
                "parameters": {"query": task, "top_k": 3},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "ticket_tool", "action": "create_ticket",
                "description": f"Create {priority}-priority {category} ticket",
                "parameters": {
                    "title": short_task,
                    "description": f"Auto-raised by AutoOps AI: {task}",
                    "priority": priority,
                    "category": category,
                    "assigned_to": "on-call-team",
                },
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Alert on-call team immediately",
                "parameters": {
                    "team": "ops",
                    "message": f"[{category.upper()}] {short_task}",
                    "urgency": urgency_override,
                },
                "depends_on": [2],
            },
        ]

    # ── INVOICE ───────────────────────────────────────────────────────────────
    if workflow_type == "invoice":
        order_id    = ctx.get("order_id",    "ORD-MOCK-001")
        customer_id = ctx.get("customer_id", "CUST-MOCK-001")
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "database_tool", "action": "query",
                "description": "Fetch order details for invoice generation",
                "parameters": {"table": "orders", "filters": {"order_id": order_id}, "limit": 1},
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "invoice_tool", "action": "generate_invoice",
                "description": f"Generate invoice for order {order_id}",
                "parameters": {"order_id": order_id, "customer_id": customer_id},
                "depends_on": [1],
            },
            {
                "step_number": 3, "agent": "executor",
                "tool": "invoice_tool", "action": "send_invoice",
                "description": "Email invoice to customer",
                "parameters": {
                    "invoice_id": ctx.get("invoice_id", "INV-MOCK-001"),
                    "email": "customer@example.com",
                },
                "depends_on": [2],
            },
            {
                "step_number": 4, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify finance team that invoice was sent",
                "parameters": {
                    "team": "finance",
                    "message": f"Invoice sent for order {order_id}: {short_task}",
                    "urgency": "normal",
                },
                "depends_on": [3],
            },
        ]

    # ── DATABASE ──────────────────────────────────────────────────────────────
    if workflow_type == "database":
        task_lower = task.lower()
        action = "insert" if any(w in task_lower for w in ["insert", "add", "create", "new"]) \
            else "update"  if any(w in task_lower for w in ["update", "edit", "change", "modify"]) \
            else "query"
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "database_tool", "action": action,
                "description": f"Perform database {action} operation",
                "parameters": {
                    "table":     "orders",
                    "filters":   {},
                    "limit":     10,
                    "record_id": ctx.get("order_id", "REC-MOCK-001"),
                    "data":      {"updated_by": "autoops", "task": short_task},
                },
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Notify data team of database operation",
                "parameters": {
                    "team": "data",
                    "message": f"DB {action} completed: {short_task}",
                    "urgency": "normal",
                },
                "depends_on": [1],
            },
        ]

    # ── EMAIL / NOTIFICATION ──────────────────────────────────────────────────
    if workflow_type == "email":
        return [
            {
                "step_number": 1, "agent": "executor",
                "tool": "notification_tool", "action": "send_email",
                "description": f"Send notification email: {short_task}",
                "parameters": {
                    "to":      "team@company.com",
                    "subject": f"AutoOps Notification: {short_task}",
                    "body":    task,
                },
                "depends_on": [],
            },
            {
                "step_number": 2, "agent": "executor",
                "tool": "notification_tool", "action": "notify_team",
                "description": "Also alert team via Slack/push",
                "parameters": {
                    "team":    "ops",
                    "message": short_task,
                    "urgency": urgency,
                },
                "depends_on": [1],
            },
        ]

    # ── GENERAL (fallback) ────────────────────────────────────────────────────
    return [
        {
            "step_number": 1, "agent": "executor",
            "tool": "knowledge_tool", "action": "search",
            "description": f"Search knowledge base for relevant guidance",
            "parameters": {"query": task, "top_k": 3},
            "depends_on": [],
        },
        {
            "step_number": 2, "agent": "executor",
            "tool": "ticket_tool", "action": "create_ticket",
            "description": "Raise a ticket so the task is tracked",
            "parameters": {
                "title":       short_task,
                "description": task,
                "priority":    priority,
                "category":    "general",
            },
            "depends_on": [1],
        },
        {
            "step_number": 3, "agent": "executor",
            "tool": "notification_tool", "action": "notify_team",
            "description": "Notify ops team",
            "parameters": {
                "team":    "ops",
                "message": f"Task in progress: {short_task}",
                "urgency": urgency,
            },
            "depends_on": [2],
        },
    ]


def _mock_plan(task: str, feedback: str = "") -> Dict[str, Any]:
    """
    Intelligent rule-based planner used when no API key is configured.

    Detects workflow type via keyword scoring, extracts structured context
    (IDs, amounts, priority) from the task text, then builds a multi-step
    plan whose steps and parameters are specific to what the task actually
    asks for — not a generic 2-step template.
    """
    workflow_type = _infer_workflow_type(task)
    ctx           = _extract_context(task)
    steps         = _build_steps(workflow_type, task, ctx)

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