from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class WorkflowRequest(BaseModel):
    task: str = Field(..., description="Natural language task description", min_length=5)
    context: Optional[Dict[str, Any]] = Field(default=None, description="Extra context for the task")
    priority: str = Field(default="normal", pattern="^(low|normal|high|urgent)$")
    dry_run: bool = Field(default=False, description="Plan only, don't execute")


class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    message: str
    data: Optional[Dict[str, Any]] = None