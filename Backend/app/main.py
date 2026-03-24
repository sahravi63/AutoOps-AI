from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.health import health_router

app = FastAPI(
    title="AutoOps AI",
    description="Autonomous Operations Manager — Multi-Agent AI System",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(health_router)


@app.get("/")
async def root():
    return {
        "name": "AutoOps AI",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }