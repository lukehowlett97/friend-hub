from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App settings
    app_name: str = "Friend Hub Chat"
    app_version: str = "0.1.0"
    debug: bool = False
    host: str = "127.0.0.1"
    port: int = 8000

    # Database settings — all required, no hardcoded credentials
    database_host: str = "localhost"
    database_port: int = 5432
    database_user: str = "chatuser"
    database_password: str  # must be set via DATABASE_PASSWORD env var
    database_name: str = "chatapp"

    # CORS — dev origins only; override via CORS_ORIGINS env var in production
    cors_origins: list = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # WebSocket limits
    ws_max_message_bytes: int = 2000
    ws_rate_limit_messages: int = 10
    ws_rate_limit_window_seconds: int = 5

    # Local photo uploads
    photo_upload_dir: str = "runtime/uploads/photos"
    photo_max_upload_bytes: int = 5 * 1024 * 1024
    photo_storage_warn_bytes: int = 20 * 1024 * 1024 * 1024
    photo_storage_max_bytes: int = 28 * 1024 * 1024 * 1024
    photo_display_max_width: int = 1600
    photo_thumbnail_max_width: int = 480
    photo_jpeg_quality: int = 82

    # Local developer-run Messenger imports. Relative paths resolve from repo root.
    messenger_export_root: str | None = None
    messenger_chat_folder: str | None = None
    messenger_room_id: str | None = None
    messenger_sender_map: str | None = None

    # Optional local image embedding worker. ML dependencies are loaded only by
    # the worker/model wrapper, not by the web app at startup.
    image_embeddings_enabled: bool = False
    image_embeddings_model_name: str = "ViT-B-32"
    image_embeddings_model_version: str = "laion2b_s34b_b79k"
    image_embeddings_device: str = "auto"
    image_embeddings_batch_size: int = 8
    image_embeddings_max_retries: int = 3

    # Private beta auth. Override INVITE_CODE outside local development.
    invite_code: str = "friend-hub-dev"

    # Public base URL used to build shareable invite links (e.g. https://friendhub.chat).
    # No trailing slash. Override via APP_BASE_URL in production.
    app_base_url: str = "http://localhost:5173"

    # AI API
    ai_api_key: str | None = None
    ai_api_provider: str = "openrouter"
    ai_default_chat_model: str = "nvidia/nemotron-3-nano-30b-a3b:free"
    ai_image_model: str = "black-forest-labs/FLUX-1-schnell:free"
    ai_image_generation_enabled: bool = False
    ai_hub_rate_limit_per_minute: int = 5
    ai_monthly_budget_cents: int = 0    # 0 = not configured
    ai_daily_summary_enabled: bool = True

    # Chat embeddings (semantic search). Worker-only ML/network calls; off by default.
    ai_enable_chat_embeddings: bool = False
    ai_embedding_provider: str = "ollama"  # fake | ollama | openai
    ai_embedding_model: str = "nomic-embed-text"
    ai_embedding_api_key: str | None = None  # openai provider only
    ai_embedding_base_url: str = "https://api.openai.com"  # openai-compatible base
    ai_embedding_max_retries: int = 3
    ai_embedding_message_batch_size: int = 15  # consecutive messages per batch
    ai_embedding_batch_flush_hours: int = 6  # embed a partial tail batch after this age
    ai_retrieval_top_k: int = 24  # hard cap on vector hits per query
    # nomic-embed-text cosine scores cluster high. Measured on real group data:
    # related content 0.55-0.63, unrelated 0.46-0.50 — 0.50 is the boundary.
    ai_retrieval_similarity_floor: float = 0.50

    # Topic detection (Batch 1). Offline semantic clusters over chat embeddings;
    # labels are deterministic placeholders until LLM refinement exists.
    ai_topic_detection_enabled: bool = False
    ai_topic_similarity_threshold: float = 0.62
    ai_topic_min_cluster_batches: int = 2
    ai_topic_max_batches_per_run: int = 1000
    ai_topic_hard_gap_minutes: int = 120
    ai_topic_soft_gap_minutes: int = 30
    ai_topic_max_topic_duration_hours: int = 6
    ai_topic_detection_version: str = "v2-semantic-time-cluster"
    ai_topic_llm_refinement_enabled: bool = False
    ai_topic_llm_provider: str = "fake"  # fake | ollama | openrouter
    ai_topic_llm_model: str = "fake"
    ai_topic_llm_max_segments: int = 8
    ai_topic_llm_max_excerpt_chars: int = 500

    # Hub Bot Lab AI settings
    ai_lab_provider: str = "fake"  # fake | ollama | openrouter (auto-upgrades to openrouter when ai_api_key is set)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout: int = 60

    # Push notifications VAPID keys
    vapid_private_key: str | None = None
    vapid_public_key: str | None = None
    vapid_subject: str = "mailto:admin@friendhub.chat"

    # Try app/.env (when CWD is backend/) then .env as fallback
    model_config = SettingsConfigDict(
        env_file=("app/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings():
    return Settings()


def get_photo_upload_path() -> Path:
    upload_dir = Path(get_settings().photo_upload_dir)
    if upload_dir.is_absolute():
        return upload_dir

    backend_root = Path(__file__).resolve().parents[1]
    return backend_root / upload_dir


def resolve_repo_path(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if path.is_absolute():
        return path

    repo_root = Path(__file__).resolve().parents[2]
    return repo_root / path
