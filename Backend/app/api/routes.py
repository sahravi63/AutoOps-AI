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
from datetime import datetime
from typing import Optional

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.agents.memory_agent import memory_agent
from app.services.agent_service import (
    run_autonomous_workflow,
    run_autonomous_workflow_streaming,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/workflow", tags=["Workflow"])


class WorkflowRequest(BaseModel):
    task: str
    context: Optional[dict] = None


# ── Standard JSON endpoint (blocking — waits for full autonomous loop) ────────
@router.post("/run")
async def execute_workflow(req: WorkflowRequest):
    """
    Run the full autonomous loop (Think → Plan → Execute → Review → Update)
    and return the complete result as JSON.
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


# ── Memory endpoints ───────────────────────────────────────────────────────────
@router.get("/memory/stats")
async def memory_stats():
    """Return current memory store statistics."""
    return memory_agent.get_stats()


@router.get("/memory/search")
async def memory_search(q: str, top_k: int = 3):
    """Search the memory store for similar past workflows."""
    return {"results": memory_agent.search(q, top_k)}
