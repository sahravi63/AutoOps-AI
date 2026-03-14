from datetime import datetime
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid


class ScreeningDecision(str, Enum):
    SHORTLISTED = "shortlisted"
    REJECTED = "rejected"
    REVIEW = "needs_review"


class ResumeScore(BaseModel):
    overall: float = Field(..., ge=0, le=100)
    skills_match: float = Field(..., ge=0, le=100)
    experience_match: float = Field(..., ge=0, le=100)
    education_match: float = Field(..., ge=0, le=100)
    culture_fit: float = Field(..., ge=0, le=100)


class ResumeCandidate(BaseModel):
    candidate_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    filename: str
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    raw_text: str
    score: Optional[ResumeScore] = None
    decision: Optional[ScreeningDecision] = None
    strengths: List[str] = []
    weaknesses: List[str] = []
    summary: Optional[str] = None
    screened_at: Optional[datetime] = None


class ScreeningJobRequest(BaseModel):
    job_title: str
    job_description: str
    required_skills: List[str] = []
    preferred_skills: List[str] = []
    min_experience_years: int = 0
    education_requirement: Optional[str] = None
    shortlist_threshold: float = Field(default=70.0, ge=0, le=100)


class ScreeningJobResult(BaseModel):
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    job_request: ScreeningJobRequest
    candidates: List[ResumeCandidate] = []
    shortlisted: List[str] = []
    rejected: List[str] = []
    needs_review: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    @property
    def total_candidates(self) -> int:
        return len(self.candidates)