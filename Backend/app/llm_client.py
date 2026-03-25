"""
AutoOps AI — Multi-Provider LLM Client
========================================
Supports Anthropic, Groq, and HuggingFace Inference API.
All API keys are OPTIONAL — provide any one (or more) and the client
picks the first that works.  If none are set, callers fall back to the
built-in rule-based mock.

Priority order (first key found wins):
  1. Anthropic  (claude-sonnet / claude-haiku)
  2. Groq       (llama-3 / mixtral — fast & free tier available)
  3. HuggingFace Inference API (free tier, slower)
  4. None → mock mode

Usage:
    from app.llm_client import get_llm_client
    client = get_llm_client()
    if client:
        text = client.complete(system_prompt, user_prompt, max_tokens=1000)
    else:
        # use mock
"""

import os
import json
import requests
from typing import Optional
from app.config.settings import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class LLMClient:
    provider: str = "base"

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

class AnthropicClient(LLMClient):
    provider = "anthropic"

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = getattr(settings, "CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text.strip()


# ---------------------------------------------------------------------------
# Groq  (OpenAI-compatible endpoint, generous free tier)
# ---------------------------------------------------------------------------

class GroqClient(LLMClient):
    provider = "groq"
    # Models available on the free tier as of 2026-03
    MODELS = [
        "llama-3.3-70b-versatile",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
    ]

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._model = getattr(settings, "GROQ_MODEL", self.MODELS[0])

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type":  "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()


# ---------------------------------------------------------------------------
# HuggingFace Inference API  (free tier; slower but always available)
# ---------------------------------------------------------------------------

class HuggingFaceClient(LLMClient):
    provider = "huggingface"
    # Models that handle instruction-following well on the free tier
    DEFAULT_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._model = getattr(settings, "HF_MODEL", self.DEFAULT_MODEL)

    def complete(self, system: str, user: str, max_tokens: int = 1500) -> str:
        # HF chat-completion format (works for instruct models)
        prompt = f"<s>[INST] {system}\n\n{user} [/INST]"
        payload = {
            "inputs": prompt,
            "parameters": {
                "max_new_tokens": max_tokens,
                "temperature": 0.2,
                "return_full_text": False,
            },
        }
        url = f"https://api-inference.huggingface.co/models/{self._model}"
        resp = requests.post(
            url,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            return data[0].get("generated_text", "").strip()
        return str(data).strip()


# ---------------------------------------------------------------------------
# Factory — returns the first working client, or None for mock mode
# ---------------------------------------------------------------------------

def _try_anthropic() -> Optional[LLMClient]:
    key = settings.ANTHROPIC_API_KEY or os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        return None
    try:
        c = AnthropicClient(key)
        logger.info("[LLMClient] Using Anthropic Claude")
        return c
    except Exception as e:
        logger.warning(f"[LLMClient] Anthropic init failed: {e}")
        return None


def _try_groq() -> Optional[LLMClient]:
    key = getattr(settings, "GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    if not key:
        return None
    try:
        c = GroqClient(key)
        logger.info("[LLMClient] Using Groq")
        return c
    except Exception as e:
        logger.warning(f"[LLMClient] Groq init failed: {e}")
        return None


def _try_huggingface() -> Optional[LLMClient]:
    key = getattr(settings, "HF_API_KEY", "") or os.getenv("HF_API_KEY", "")
    if not key:
        return None
    try:
        c = HuggingFaceClient(key)
        logger.info("[LLMClient] Using HuggingFace Inference API")
        return c
    except Exception as e:
        logger.warning(f"[LLMClient] HuggingFace init failed: {e}")
        return None


# Module-level singleton (initialised once)
_client_cache: Optional[LLMClient] = None
_cache_ready = False


def get_llm_client() -> Optional[LLMClient]:
    """
    Return the first available LLM client (Anthropic → Groq → HuggingFace).
    Returns None if no API keys are configured → callers use mock mode.
    Result is cached after the first call.
    """
    global _client_cache, _cache_ready
    if _cache_ready:
        return _client_cache

    _client_cache = _try_anthropic() or _try_groq() or _try_huggingface()
    _cache_ready = True

    if _client_cache is None:
        logger.warning(
            "[LLMClient] No API keys found (ANTHROPIC_API_KEY / GROQ_API_KEY / HF_API_KEY). "
            "Running in MOCK mode. Add any key to .env to enable real LLM."
        )
    return _client_cache


def llm_complete(system: str, user: str, max_tokens: int = 1500) -> Optional[str]:
    """
    Convenience wrapper.  Returns the LLM text or None if in mock mode.
    """
    client = get_llm_client()
    if client is None:
        return None
    try:
        return client.complete(system, user, max_tokens)
    except Exception as e:
        logger.error(f"[LLMClient] {client.provider} call failed: {e}")
        return None
