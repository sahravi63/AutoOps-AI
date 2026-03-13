from fastapi import FastAPI
from app.api.routes import router
from app.api.resume_routes import resume_router
from app.api.health import health_router

app = FastAPI(title="AutoOps AI")

app.include_router(router)
app.include_router(resume_router)
app.include_router(health_router)