import asyncio
from datetime import datetime
from typing import Any, Dict, List

from app.models.workflow_model import AgentStep
from app.tools.payment_tool import PaymentTool
from app.tools.report_tool import ReportTool
from app.tools.invoice_tool import InvoiceTool
from app.tools.notification_tool import NotificationTool
from app.tools.database_tool import DatabaseTool
from app.tools.resume_tool import ResumeTool
from app.utils.logger import get_logger

logger = get_logger(__name__)

TOOL_MAP = {
    "payment_tool": PaymentTool,
    "report_tool": ReportTool,
    "invoice_tool": InvoiceTool,
    "notification_tool": NotificationTool,
    "database_tool": DatabaseTool,
    "resume_tool": ResumeTool,
}


class ExecutorAgent:
    def __init__(self):
        self._tool_instances: Dict[str, Any] = {}

    def _get_tool(self, tool_name: str):
        if tool_name not in self._tool_instances:
            cls = TOOL_MAP.get(tool_name)
            if not cls:
                raise ValueError(f"Unknown tool: {tool_name}")
            self._tool_instances[tool_name] = cls()
        return self._tool_instances[tool_name]

    async def execute_step(self, step: AgentStep) -> AgentStep:
        step.started_at = datetime.utcnow()
        step.status = "running"
        logger.info(f"Executing step {step.step_id}: {step.action}")

        try:
            tool = self._get_tool(step.input_data.get("tool", ""))
            action = step.input_data.get("action", "execute")
            params = step.input_data.get("parameters", {})

            method = getattr(tool, action, None)
            if not method:
                raise AttributeError(f"Tool '{tool.__class__.__name__}' has no method '{action}'")

            if asyncio.iscoroutinefunction(method):
                result = await method(**params)
            else:
                result = await asyncio.to_thread(method, **params)

            step.output_data = result
            step.status = "completed"
            logger.info(f"Step {step.step_id} completed successfully")

        except Exception as e:
            step.status = "failed"
            step.error = str(e)
            logger.error(f"Step {step.step_id} failed: {e}")
        finally:
            step.completed_at = datetime.utcnow()

        return step

    async def execute_plan(self, plan: Dict[str, Any]) -> List[AgentStep]:
        steps_config = plan.get("steps", [])
        completed: Dict[int, AgentStep] = {}

        for step_conf in steps_config:
            step = AgentStep(
                agent=step_conf.get("agent", "executor"),
                action=step_conf.get("action", ""),
                input_data={
                    "tool": step_conf.get("tool", ""),
                    "action": step_conf.get("action", "execute"),
                    "parameters": step_conf.get("parameters", {})
                }
            )
            step = await self.execute_step(step)
            completed[step_conf["step_number"]] = step

        return list(completed.values())