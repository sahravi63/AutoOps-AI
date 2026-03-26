"""
Memory agent with file persistence.
Stores problem-solution pairs in JSON file for durability.
"""
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# File-based persistence
MEMORY_FILE = "memory_store.json"


class MemoryAgent:
    def __init__(self):
        self._store: List[Dict[str, Any]] = []
        self._load_from_file()
        # Seed with initial knowledge if empty
        if not self._store:
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
            self._save_to_file()

    def _load_from_file(self) -> None:
        """Load memory from persistent JSON file."""
        if Path(MEMORY_FILE).exists():
            try:
                with open(MEMORY_FILE, "r") as f:
                    self._store = json.load(f)
                logger.info(f"[Memory] Loaded {len(self._store)} entries from disk")
            except Exception as e:
                logger.warning(f"[Memory] Failed to load: {e}; starting fresh")
                self._store = []
        else:
            self._store = []

    def _save_to_file(self) -> None:
        """Persist memory to JSON file."""
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump(self._store, f, indent=2)
        except Exception as e:
            logger.error(f"[Memory] Failed to save: {e}")

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
        self._save_to_file()
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