from fastapi import APIRouter
from datetime import datetime

health_router = APIRouter(tags=["Health"])


@health_router.get("/health")
async def health():
    return {"status": "ok", "service": "AutoOps AI", "ts": datetime.utcnow().isoformat()}