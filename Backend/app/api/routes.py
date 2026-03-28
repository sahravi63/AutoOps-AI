"""
AutoOps AI — FastAPI Routes
============================
REST + Server-Sent Events endpoints.

/workflow/run    → Standard JSON, full autonomous loop (blocking)
/workflow/stream → SSE streaming, full autonomous loop (real-time)
/workflow/memory/stats  → Memory stats
/workflow/memory/search → Memory search
"""

import json
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.memory_agent import memory_agent
from app.services.agent_service import (
    run_autonomous_workflow,
    run_autonomous_workflow_streaming,
)
from app.tools.all_tools import QueueTool
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/workflow", tags=["Workflow"])


class WorkflowRequest(BaseModel):
    task: str = Field(..., max_length=10000, description="Task description for autonomous workflow")
    context: Optional[dict] = Field(default=None, max_items=100, description="Optional context data")


class QueueRequest(BaseModel):
    task: str = Field(..., max_length=10000, description="Task description for autonomous workflow")
    context: Optional[dict] = Field(default=None, max_items=100, description="Optional context data")
    source: str = Field(default="webhook", description="Task trigger source")
    max_attempts: int = Field(default=3, ge=1, le=10, description="Number of retry attempts before dead-letter")


queue_tool = QueueTool()


# ── Standard JSON endpoint (blocking — waits for full autonomous loop) ────────
@router.post("/run")
async def execute_workflow(req: WorkflowRequest):
    """
    Run the full autonomous loop (Think → Plan → Execute → Review → Update)
    and return the complete result as JSON.
    Rate limited: 10 requests/minute per IP.
    """
    result = await run_autonomous_workflow(req.task, req.context)
    return result.model_dump(mode="json")


# ── Streaming SSE endpoint (real-time step-by-step updates) ───────────────────
@router.post("/stream")
async def stream_workflow(req: WorkflowRequest):
    """
    Run the autonomous loop and stream each event in real-time via SSE.
    Events: start, think, memory_recall, loop_start, plan, plan_ready,
            execute, step_start, step_done, review, review_done,
            update, memory_stored, complete, error
    Rate limited: 5 requests/minute per IP.
    """

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"

    async def event_generator():
        try:
            async for event_name, data in run_autonomous_workflow_streaming(
                req.task, req.context
            ):
                yield sse(event_name, data)
        except Exception as e:
            logger.error(f"Streaming error: {e}", exc_info=True)
            yield sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/enqueue")
async def enqueue_workflow(req: QueueRequest):
    """Enqueue a durable workflow job from an external trigger or webhook."""
    job = queue_tool.enqueue_task(
        task=req.task,
        context=req.context or {},
        source=req.source,
        max_attempts=req.max_attempts,
    )
    return {"status": "enqueued", **job}


@router.post("/process-next")
async def process_next_job():
    """Process the next ready workflow job from the durable queue."""
    job = queue_tool.fetch_next_task()
    if not job:
        return {"status": "idle", "message": "No pending jobs ready to run."}

    queue_tool.mark_job_started(job["job_id"])
    result = await run_autonomous_workflow(job["task"], job["context"], workflow_id=job["job_id"])
    success = result.status == "completed"
    retry_delay = 60 * (2 ** max(0, result.loops_used - 1))
    queue_tool.mark_job_result(
        job["job_id"], success,
        error=result.review.get("summary", "") if not success else "",
        retry_delay_seconds=retry_delay,
    )
    return {
        "job_id": job["job_id"],
        "status": result.status,
        "loops_used": result.loops_used,
        "review": result.review,
    }


@router.get("/queue")
async def queue_status(status: str = "pending"):
    """List durable workflow queue jobs by status."""
    return queue_tool.list_jobs(status)


# ── Memory endpoints ───────────────────────────────────────────────────────────
@router.get("/memory/stats")
async def memory_stats():
    """Return current memory store statistics."""
    return memory_agent.get_stats()


@router.get("/memory/search")
async def memory_search(q: str, top_k: int = 3):
    """Search the memory store for similar past workflows."""
    return {"results": memory_agent.search(q, top_k)}
