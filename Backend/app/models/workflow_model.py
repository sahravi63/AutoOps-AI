"""
AutoOps AI — Data Models
"""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
import uuid


class AgentStep(BaseModel):
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    step_number: int = 0
    agent: str = "executor"
    tool: str = ""
    action: str = ""
    input_data: Dict[str, Any] = {}
    output_data: Optional[Dict[str, Any]] = None
    status: str = "pending"   # pending | running | completed | failed
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def duration_ms(self) -> Optional[int]:
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None


class WorkflowStep(BaseModel):
    step_number: int = Field(..., ge=1)
    agent: str = "executor"
    tool: str
    action: str
    description: str = ""
    parameters: Dict[str, Any] = {}
    depends_on: List[int] = []


class WorkflowPlan(BaseModel):
    task_summary: str
    workflow_type: str = Field(default="payment_failure_remediation")
    steps: List[WorkflowStep]
    estimated_duration_seconds: int = Field(default=0, ge=0)
    risk_level: str = Field(default="medium")
    retry_reason: str = ""
    mode: str = "mock"
    extracted_context: Dict[str, Any] = {}


class WorkflowResult(BaseModel):
    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:12])
    task: str
    plan: Dict[str, Any] = {}
    steps: List[AgentStep] = []
    review: Dict[str, Any] = {}
    status: str = "pending"     # pending | running | completed | partial | failed
    loops_used: int = 0         # How many autonomy loops were used
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
