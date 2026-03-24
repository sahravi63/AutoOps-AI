"""
AutoOps AI — Workflow Service (compatibility shim)
====================================================
This module used to contain the workflow logic directly.
It now delegates to agent_service, which has the full autonomous loop.

Kept for backward compatibility — any code that imports run_workflow()
will continue to work unchanged.
"""

from typing import Any, Dict, Optional

from app.services.agent_service import run_autonomous_workflow
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def run_workflow(
    task: str,
    context: Optional[Dict[str, Any]] = None,
) -> Any:
    """
    Backward-compatible wrapper around run_autonomous_workflow.
    Returns the WorkflowResult object.
    """
    return await run_autonomous_workflow(task, context)
