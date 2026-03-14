import json
from typing import Any, Dict, List

import anthropic

from app.config.settings import settings
from app.models.workflow_model import AgentStep
from app.utils.logger import get_logger

logger = get_logger(__name__)

REVIEWER_SYSTEM = """You are a quality-review agent in AutoOps AI.
You review the output of executed workflow steps and determine if the overall workflow succeeded.

Respond ONLY with valid JSON:
{
  "passed": true,
  "confidence": 0.95,
  "summary": "All steps completed successfully.",
  "issues": [],
  "recommendations": []
}"""


class ReviewerAgent:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def review(self, task: str, plan: Dict[str, Any],
               steps: List[AgentStep]) -> Dict[str, Any]:
        logger.info("Reviewing workflow execution...")

        steps_summary = [
            {
                "action": s.action,
                "status": s.status,
                "output": s.output_data,
                "error": s.error,
            }
            for s in steps
        ]

        message = self.client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=512,
            system=REVIEWER_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Original task: {task}\n\n"
                    f"Plan risk level: {plan.get('risk_level', 'unknown')}\n\n"
                    f"Execution results:\n{json.dumps(steps_summary, indent=2, default=str)}"
                )
            }]
        )

        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        review = json.loads(raw.strip())
        logger.info(f"Review complete. Passed: {review.get('passed')}")
        return review