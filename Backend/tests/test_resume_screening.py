"""
AutoOps AI — Resume screening tool tests
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.tools.all_tools import ResumeTool


def test_resume_screen_returns_results():
    tool = ResumeTool()
    result = tool.screen_resumes(
        job_title="Python Developer",
        requirements=["Python", "FastAPI"],
        resume_count=10,
    )
    assert "candidates_reviewed" in result
    assert "shortlisted" in result
    assert result["candidates_reviewed"] == 10


def test_resume_screen_shortlists_some():
    tool = ResumeTool()
    result = tool.screen_resumes(
        job_title="Senior ML Engineer",
        requirements=["Python", "ML", "AWS"],
        resume_count=20,
    )
    # shortlist should be 0..resume_count
    assert 0 <= result["shortlisted_count"] <= 20


def test_resume_screen_no_requirements():
    tool = ResumeTool()
    result = tool.screen_resumes(job_title="Generalist", requirements=[], resume_count=5)
    assert result["candidates_reviewed"] == 5
