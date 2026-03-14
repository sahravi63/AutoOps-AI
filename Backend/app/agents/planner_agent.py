import json
from typing import Any, Dict, List

import anthropic

from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

PLANNER_SYSTEM = """You are a planning agent in an autonomous operations system called AutoOps AI.
Your job is to analyze a user's task and create a structured execution plan.

You have access to these tools:
- payment_tool: process payments, refunds, subscriptions
- report_tool: generate analytics and business reports
- invoice_tool: create, send, and manage invoices
- notification_tool: send emails, SMS, push notifications
- database_tool: query and update business databases
- resume_tool: screen and score resumes against job descriptions

Respond ONLY with valid JSON in this format:
{
  "task_summary": "Brief description of the task",
  "steps": [
    {
      "step_number": 1,
      "agent": "executor",
      "tool": "tool_name",
      "action": "action description",
      "parameters": {},
      "depends_on": []
    }
  ],
  "estimated_duration_seconds": 30,
  "risk_level": "low|medium|high"
}"""


class PlannerAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def plan(self, task: str, context: Dict[str, Any] = None,
             memory_hints: List[Dict] = None) -> Dict[str, Any]:
        logger.info(f"Planning task: {task[:80]}...")

        context_str = ""
        if context:
            context_str = f"\n\nContext:\n{json.dumps(context, indent=2)}"

        memory_str = ""
        if memory_hints:
            memory_str = "\n\nSimilar past workflows:\n" + "\n".join(
                f"- {h['document'][:200]}" for h in memory_hints[:2]
            )

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=1024,
            system=PLANNER_SYSTEM,
            messages=[{
                "role": "user",
                "content": f"Task: {task}{context_str}{memory_str}"
            }]
        )

        raw = message.content[0].text.strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        plan = json.loads(raw.strip())
        logger.info(f"Plan created with {len(plan['steps'])} steps")
        return plan