from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent: str
    action: str
    input_data: Dict[str, Any] = {}
    output_data: Optional[Dict[str, Any]] = None
    status: str = "pending"
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class WorkflowResult(BaseModel):
    workflow_id: str
    status: WorkflowStatus
    steps: List[AgentStep] = []
    final_output: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds()
        return None