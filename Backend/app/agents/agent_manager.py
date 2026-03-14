from datetime import datetime
from typing import Any, Dict, Optional
import uuid

from app.agents.planner_agent import PlannerAgent
from app.agents.executor_agent import ExecutorAgent
from app.agents.reviewer_agent import ReviewerAgent
from app.memory.memory_manager import memory_manager
from app.models.workflow_model import WorkflowResult, WorkflowStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AgentManager:
    def __init__(self):
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent()
        self.reviewer = ReviewerAgent()

    async def run_workflow(self, task: str, context: Optional[Dict[str, Any]] = None,
                           dry_run: bool = False) -> WorkflowResult:
        workflow_id = str(uuid.uuid4())
        result = WorkflowResult(workflow_id=workflow_id, status=WorkflowStatus.PLANNING)
        logger.info(f"[{workflow_id}] Starting workflow: {task[:80]}")

        try:
            # Recall similar past workflows
            memory_hints = memory_manager.recall_similar_workflows(task, n=2)

            # Plan
            result.status = WorkflowStatus.PLANNING
            plan = self.planner.plan(task, context=context, memory_hints=memory_hints)

            if dry_run:
                result.status = WorkflowStatus.COMPLETED
                result.final_output = {"plan": plan, "dry_run": True}
                result.completed_at = datetime.utcnow()
                return result

            # Execute
            result.status = WorkflowStatus.EXECUTING
            steps = await self.executor.execute_plan(plan)
            result.steps = steps

            # Review
            result.status = WorkflowStatus.REVIEWING
            review = self.reviewer.review(task, plan, steps)

            result.status = (
                WorkflowStatus.COMPLETED if review.get("passed")
                else WorkflowStatus.FAILED
            )
            result.final_output = {
                "plan": plan,
                "review": review,
                "step_count": len(steps),
            }
            result.completed_at = datetime.utcnow()

            # Persist to memory
            memory_manager.store_workflow(
                workflow_id=workflow_id,
                task=task,
                result=result.final_output,
                status=result.status.value
            )

            logger.info(f"[{workflow_id}] Workflow finished: {result.status}")

        except Exception as e:
            result.status = WorkflowStatus.FAILED
            result.error = str(e)
            result.completed_at = datetime.utcnow()
            logger.error(f"[{workflow_id}] Workflow failed: {e}")

        return result


agent_manager = AgentManager()