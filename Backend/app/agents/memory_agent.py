"""
Simple in-memory knowledge store (replace with ChromaDB/Pinecone in production).
"""
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryAgent:
    def __init__(self):
        self._store: List[Dict[str, Any]] = []
        # Seed with some initial knowledge
        self._store.extend([
            {
                "id": "mem-001",
                "category": "payment",
                "problem": "Customer payment failed but money was deducted",
                "solution": "Check transaction in gateway → verify deduction → initiate refund → create ticket → notify customer",
                "timestamp": "2026-01-10T09:00:00Z",
                "success_count": 23,
            },
            {
                "id": "mem-002",
                "category": "delivery",
                "problem": "Order shows delivered but customer hasn't received",
                "solution": "Check GPS proof → contact courier API → if unverified → reship or refund within 24h",
                "timestamp": "2026-02-05T14:30:00Z",
                "success_count": 15,
            },
        ])

    def search(self, query: str, top_k: int = 3) -> List[Dict]:
        query_lower = query.lower()
        scored = []
        for entry in self._store:
            score = 0
            text = f"{entry.get('problem', '')} {entry.get('solution', '')} {entry.get('category', '')}".lower()
            for word in query_lower.split():
                if word in text:
                    score += 1
            if score > 0:
                scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for _, entry in scored[:top_k]:
            results.append({
                "document": f"[{entry['category']}] Problem: {entry['problem']} → Solution: {entry['solution']}",
                "metadata": entry,
            })
        return results

    def store(self, category: str, problem: str,
              solution: str, workflow_id: str = "") -> str:
        mem_id = f"mem-{len(self._store)+1:03d}"
        self._store.append({
            "id": mem_id,
            "category": category,
            "problem": problem,
            "solution": solution,
            "workflow_id": workflow_id,
            "timestamp": datetime.utcnow().isoformat(),
            "success_count": 1,
        })
        logger.info(f"[MemoryAgent] Stored memory {mem_id}: {problem[:40]}")
        return mem_id

    def get_stats(self) -> Dict[str, Any]:
        categories = {}
        for entry in self._store:
            cat = entry.get("category", "general")
            categories[cat] = categories.get(cat, 0) + 1
        return {
            "total_memories": len(self._store),
            "categories": categories,
        }


# Global singleton
memory_agent = MemoryAgent()