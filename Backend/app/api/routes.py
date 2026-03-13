from fastapi import APIRouter
from app.services.workflow_service import run_workflow

router = APIRouter(prefix="/workflow")

@router.post("/")
def execute_workflow(data: dict):
    task = data.get("task")
    result = run_workflow(task)
    return result