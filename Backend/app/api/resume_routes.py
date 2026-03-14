from fastapi import APIRouter, UploadFile, File
from app.services.resume_service import screen_resume

resume_router = APIRouter(prefix="/resume")

@resume_router.post("/screen")
async def upload_resume(file: UploadFile = File(...)):
    result = await screen_resume(file)
    return result