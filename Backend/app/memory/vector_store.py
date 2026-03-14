from typing import Any, Dict, List, Optional
import chromadb
from chromadb.config import Settings as ChromaSettings
from sentence_transformers import SentenceTransformer

from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class VectorStore:
    def __init__(self):
        self._client: Optional[chromadb.Client] = None
        self._model: Optional[SentenceTransformer] = None

    def _get_client(self) -> chromadb.Client:
        if not self._client:
            self._client = chromadb.PersistentClient(
                path=settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        return self._client

    def _get_model(self) -> SentenceTransformer:
        if not self._model:
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def _embed(self, texts: List[str]) -> List[List[float]]:
        return self._get_model().encode(texts).tolist()

    def upsert(self, collection: str, ids: List[str], documents: List[str],
               metadatas: Optional[List[Dict]] = None) -> None:
        col = self._get_client().get_or_create_collection(collection)
        embeddings = self._embed(documents)
        col.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas or [{} for _ in ids]
        )
        logger.info(f"Upserted {len(ids)} docs into '{collection}'")

    def query(self, collection: str, query_text: str, n_results: int = 5,
              where: Optional[Dict] = None) -> List[Dict[str, Any]]:
        col = self._get_client().get_or_create_collection(collection)
        embedding = self._embed([query_text])
        results = col.query(
            query_embeddings=embedding,
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"]
        )
        items = []
        for i, doc_id in enumerate(results["ids"][0]):
            items.append({
                "id": doc_id,
                "document": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            })
        return items

    def delete_collection(self, collection: str) -> None:
        self._get_client().delete_collection(collection)
        logger.info(f"Deleted collection '{collection}'")


vector_store = VectorStore()