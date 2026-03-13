from app.agents.planner_agent import generate_plan
from app.agents.executor_agent import execute_step
from app.agents.reviewer_agent import review_results

def run_workflow(task: str):

    plan = generate_plan(task)

    execution_logs = []

    for step in plan:
        result = execute_step(step)
        execution_logs.append(result)

    review = review_results(execution_logs)

    return {
        "task": task,
        "plan": plan,
        "execution": execution_logs,
        "review": review
    }