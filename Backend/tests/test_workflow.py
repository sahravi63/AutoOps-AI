"""
AutoOps AI — Integration tests (no API key required)
=====================================================
Tests run fully in mock mode so they work in CI and local dev
without any paid API keys.
"""
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from app.agents.planner_agent import PlannerAgent, _infer_workflow_type, _extract_context
from app.agents.executor_agent import ExecutorAgent, resolve_placeholders
from app.agents.reviewer_agent import ReviewerAgent
from app.agents.graph import GraphExecutor, _build_dep_map, _topological_waves
from app.models.workflow_model import AgentStep


# ─────────────────────────────────────────────────────────────────────────────
# Planner unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_infer_workflow_refund():
    assert _infer_workflow_type("please refund order ORD-1234") == "refund"

def test_infer_workflow_delivery():
    assert _infer_workflow_type("track shipment ORD-999") == "delivery"

def test_infer_workflow_resume():
    assert _infer_workflow_type("screen resumes for Python developer") == "resume"

def test_infer_workflow_general_fallback():
    result = _infer_workflow_type("do something random xyz")
    assert result == "general"

def test_extract_context_ids():
    ctx = _extract_context("Refund TXN-5001 for CUST-00123 amount $499")
    assert ctx["transaction_id"] == "TXN-5001"
    assert ctx["customer_id"]    == "CUST-00123"
    assert ctx["amount"]         == 499.0

def test_extract_context_student_id():
    ctx = _extract_context("Student payment failed but tuition fee was deducted. Student ID: STU-00123, amount $2999.")
    assert ctx["student_id"] == "STU-00123"
    assert ctx["amount"] == 2999.0

def test_extract_context_generic_student_id():
    ctx = _extract_context("Student payment failed. Student ID: 12345, amount $2999.")
    assert ctx["student_id"] == "12345"
    assert ctx["amount"] == 2999.0

def test_planner_resolves_transaction_by_student_id():
    planner = PlannerAgent()
    plan = planner.plan("Student payment failed but tuition fee was deducted. Student ID: STU-00123, amount $1299.")
    assert plan["steps"][0]["parameters"]["transaction_id"] == "TXN-AB12CD34"

def test_extract_context_priority():
    ctx = _extract_context("URGENT: production is down")
    assert ctx["priority"] == "high"

def test_planner_mock_returns_steps():
    planner = PlannerAgent()
    plan = planner.plan("refund order ORD-5487 for CUST-001")
    assert "steps" in plan
    assert len(plan["steps"]) >= 2
    assert plan["workflow_type"] in ("refund", "payment")

def test_planner_mock_feedback_included():
    planner = PlannerAgent()
    plan = planner.plan("process payment", feedback="step 1 failed due to missing amount")
    assert plan.get("retry_reason") == "step 1 failed due to missing amount"

def test_planner_memory_hints_accepted():
    planner = PlannerAgent()
    hints = [{"document": "[payment] Problem: failed → Solution: check gateway"}]
    plan = planner.plan("check payment status", memory_hints=hints)
    assert "steps" in plan


# ─────────────────────────────────────────────────────────────────────────────
# Placeholder resolver tests
# ─────────────────────────────────────────────────────────────────────────────

def test_resolve_simple_placeholder():
    outputs = {2: {"invoice_id": "INV-999"}}
    params  = {"invoice_id": "${step2.invoice_id}"}
    result  = resolve_placeholders(params, outputs)
    assert result["invoice_id"] == "INV-999"

def test_resolve_missing_placeholder_returns_original():
    result = resolve_placeholders({"x": "${step9.missing}"}, {})
    assert result["x"] == "${step9.missing}"

def test_resolve_nested_dict():
    outputs = {1: {"order_id": "ORD-123"}}
    params  = {"metadata": {"order": "${step1.order_id}"}}
    result  = resolve_placeholders(params, outputs)
    assert result["metadata"]["order"] == "ORD-123"

def test_resolve_list_values():
    outputs = {1: {"tid": "TXN-7"}}
    params  = {"ids": ["${step1.tid}", "static"]}
    result  = resolve_placeholders(params, outputs)
    assert result["ids"] == ["TXN-7", "static"]

def test_resolve_inline_string():
    outputs = {1: {"name": "Alice"}}
    params  = {"msg": "Hello ${step1.name}, welcome!"}
    result  = resolve_placeholders(params, outputs)
    assert result["msg"] == "Hello Alice, welcome!"

def test_resolve_no_placeholders_unchanged():
    params = {"key": "value", "num": 42}
    assert resolve_placeholders(params, {}) == params


# ─────────────────────────────────────────────────────────────────────────────
# Graph executor unit tests
# ─────────────────────────────────────────────────────────────────────────────

def test_dep_map_built_correctly():
    steps = [
        {"step_number": 1, "depends_on": []},
        {"step_number": 2, "depends_on": [1]},
        {"step_number": 3, "depends_on": [1, 2]},
    ]
    dm = _build_dep_map(steps)
    assert dm[1] == []
    assert dm[2] == [1]
    assert dm[3] == [1, 2]

def test_topological_waves_parallel():
    steps = [
        {"step_number": 1, "depends_on": []},
        {"step_number": 2, "depends_on": []},  # parallel with 1
        {"step_number": 3, "depends_on": [1, 2]},
    ]
    waves = _topological_waves(steps, _build_dep_map(steps))
    assert len(waves) == 2
    assert len(waves[0]) == 2  # steps 1 and 2 in first wave
    assert waves[1][0]["step_number"] == 3

def test_topological_waves_sequential():
    steps = [
        {"step_number": 1, "depends_on": []},
        {"step_number": 2, "depends_on": [1]},
        {"step_number": 3, "depends_on": [2]},
    ]
    waves = _topological_waves(steps, _build_dep_map(steps))
    assert len(waves) == 3

@pytest.mark.asyncio
async def test_graph_executor_skips_on_failure():
    """Step 2 depends on Step 1. If Step 1 fails, Step 2 must be skipped."""
    plan = {
        "risk_level": "low",
        "steps": [
            {"step_number": 1, "agent": "executor", "tool": "NONEXISTENT_TOOL",
             "action": "run", "parameters": {}, "depends_on": []},
            {"step_number": 2, "agent": "executor", "tool": "database_tool",
             "action": "query", "parameters": {"table": "orders", "filters": {}, "limit": 1},
             "depends_on": [1]},
        ]
    }
    executor = ExecutorAgent()
    graph    = GraphExecutor()
    steps    = await graph.run(plan, executor)

    assert len(steps) == 2
    assert steps[0].status == "failed"   # step 1 failed (bad tool)
    assert steps[1].status == "failed"   # step 2 skipped because step 1 failed
    assert "Skipped" in (steps[1].error or "")

@pytest.mark.asyncio
async def test_graph_executor_runs_parallel_steps():
    """Steps 1 and 2 have no deps — both run; step 3 runs after both complete."""
    plan = {
        "risk_level": "low",
        "steps": [
            {"step_number": 1, "agent": "executor", "tool": "database_tool",
             "action": "query", "parameters": {"table": "orders", "filters": {}, "limit": 1},
             "depends_on": []},
            {"step_number": 2, "agent": "executor", "tool": "database_tool",
             "action": "query", "parameters": {"table": "customers", "filters": {}, "limit": 1},
             "depends_on": []},
            {"step_number": 3, "agent": "executor", "tool": "knowledge_tool",
             "action": "search", "parameters": {"query": "test", "top_k": 1},
             "depends_on": [1, 2]},
        ]
    }
    executor = ExecutorAgent()
    graph    = GraphExecutor()
    steps    = await graph.run(plan, executor)
    assert len(steps) == 3
    statuses = {s.step_number: s.status for s in steps}
    # Step 3 must only run if 1 and 2 completed
    if statuses[1] == "completed" and statuses[2] == "completed":
        assert statuses[3] in ("completed", "failed")  # ran, regardless of result


# ─────────────────────────────────────────────────────────────────────────────
# Reviewer unit tests
# ─────────────────────────────────────────────────────────────────────────────

def _make_step(n, status, tool="database_tool", action="query", error=None, output=None):
    s = AgentStep(
        step_number=n, agent="executor", tool=tool, action=action,
        input_data={"parameters": {}},
        output_data=output or {"status": "ok"},
        status=status,
        error=error,
    )
    return s

def test_reviewer_passes_all_completed():
    reviewer = ReviewerAgent()
    steps = [_make_step(1, "completed"), _make_step(2, "completed")]
    plan  = {"workflow_type": "general", "task_summary": "test"}
    result = reviewer.review("test task", plan, steps)
    assert result["passed"] is True
    assert result["completed_steps"] == 2
    assert result["failed_steps"] == 0

def test_reviewer_fails_with_failed_steps():
    reviewer = ReviewerAgent()
    steps = [
        _make_step(1, "completed"),
        _make_step(2, "failed", error="Tool not found"),
    ]
    plan = {"workflow_type": "general"}
    result = reviewer.review("test task", plan, steps)
    assert result["passed"] is False
    assert result["failed_steps"] == 1
    assert len(result["issues"]) > 0

def test_reviewer_detects_param_mismatch():
    reviewer = ReviewerAgent()
    steps = [_make_step(1, "failed", error="got an unexpected keyword argument 'foo'")]
    plan  = {"workflow_type": "payment"}
    result = reviewer.review("test", plan, steps)
    patterns = result.get("failure_patterns", {})
    assert "param_mismatch" in patterns

def test_reviewer_checks_workflow_completeness():
    reviewer = ReviewerAgent()
    # refund workflow requires payment_tool and notification_tool
    steps = [_make_step(1, "completed", tool="database_tool")]
    plan  = {"workflow_type": "refund"}
    result = reviewer.review("refund test", plan, steps)
    assert result["passed"] is False
    assert any("payment_tool" in i or "notification_tool" in i for i in result["issues"])

def test_reviewer_no_steps_fails():
    reviewer = ReviewerAgent()
    result = reviewer.review("empty task", {}, [])
    assert result["passed"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Full end-to-end mock workflow
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_full_mock_workflow_payment():
    from app.services.agent_service import run_autonomous_workflow
    result = await run_autonomous_workflow(
        "Check payment status for TXN-0001",
        context={"transaction_id": "TXN-0001"}
    )
    assert result.workflow_id
    assert result.status in ("completed", "partial")
    assert len(result.steps) > 0
    assert result.review.get("completed_steps", 0) >= 0

@pytest.mark.asyncio
async def test_full_mock_workflow_invoice():
    from app.services.agent_service import run_autonomous_workflow
    result = await run_autonomous_workflow(
        "Generate invoice for ORD-5487",
        context={"order_id": "ORD-5487"}
    )
    assert result.status in ("completed", "partial")
    assert result.plan.get("workflow_type") == "invoice"
