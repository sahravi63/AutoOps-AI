from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── LLM provider keys (ALL optional — provide any one or more) ────────
    # Priority: Anthropic → Groq → HuggingFace → mock
    ANTHROPIC_API_KEY: str = ""
    GROQ_API_KEY:      str = ""
    HF_API_KEY:        str = ""   # HuggingFace Inference API token

    # ── Model overrides (sensible defaults, change if needed) ─────────────
    CLAUDE_MODEL: str = "claude-haiku-4-5-20251001"    # cheapest Anthropic model
    GROQ_MODEL:   str = "llama-3.3-70b-versatile"       # best free-tier Groq model
    HF_MODEL:     str = "mistralai/Mistral-7B-Instruct-v0.3"

    # ── App ───────────────────────────────────────────────────────────────
    APP_NAME: str = "AutoOps AI"
    DEBUG:    bool = True

    # ── Memory / Vector store ─────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = "./chroma_db"
    EMBEDDING_MODEL:    str = "all-MiniLM-L6-v2"

    class Config:
        env_file = ".env"


settings = Settings()
