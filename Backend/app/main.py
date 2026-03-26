import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.api.health import health_router

app = FastAPI(
    title="AutoOps AI",
    description="Autonomous Operations Manager — Multi-Agent AI System",
    version="1.0.0",
)

# Rate limiting (10 req/min per IP)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429,
    content={"detail": "Rate limit exceeded. Max 10 requests per minute."},
))

# CORS — restrict to specific origins in production
allow_origins = os.getenv("ALLOW_ORIGINS", "http://localhost:3000,http://localhost:8501").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
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