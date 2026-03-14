import json
from datetime import datetime
from typing import Any, Dict, List, Optional
import uuid

from app.memory.vector_store import vector_store
from app.utils.logger import get_logger

logger = get_logger(__name__)

COLLECTION_WORKFLOWS = "workflow_memory"
COLLECTION_RESUMES = "resume_memory"


class MemoryManager:
    def store_workflow(self, workflow_id: str, task: str,
                       result: Dict[str, Any], status: str) -> None:
        doc = f"Task: {task}\nStatus: {status}\nResult: {json.dumps(result, default=str)}"
        vector_store.upsert(
            collection=COLLECTION_WORKFLOWS,
            ids=[workflow_id],
            documents=[doc],
            metadatas=[{"workflow_id": workflow_id, "status": status,
                        "timestamp": datetime.utcnow().isoformat()}]
        )

    def recall_similar_workflows(self, task: str, n: int = 3) -> List[Dict]:
        return vector_store.query(COLLECTION_WORKFLOWS, task, n_results=n)

    def store_resume(self, candidate_id: str, resume_text: str,
                     job_id: str, score: float, decision: str) -> None:
        vector_store.upsert(
            collection=COLLECTION_RESUMES,
            ids=[candidate_id],
            documents=[resume_text],
            metadatas=[{"candidate_id": candidate_id, "job_id": job_id,
                        "score": score, "decision": decision,
                        "timestamp": datetime.utcnow().isoformat()}]
        )

    def find_similar_resumes(self, resume_text: str, job_id: Optional[str] = None,
                             n: int = 5) -> List[Dict]:
        where = {"job_id": job_id} if job_id else None
        return vector_store.query(COLLECTION_RESUMES, resume_text,
                                  n_results=n, where=where)


memory_manager = MemoryManager()