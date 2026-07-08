from typing import Optional
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── API ───────────────────────────────────────────────────────────────────
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Gaussian Avatar Platform"

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # ── Cloudflare R2 ─────────────────────────────────────────────────────────
    # R2 endpoint: https://<CLOUDFLARE_ACCOUNT_ID>.r2.cloudflarestorage.com
    # Region is always "auto" for R2.
    CLOUDFLARE_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET_NAME: str = "avatar-platform"

    # Stable public URL for the bucket.
    # Set CLOUDFLARE_PUBLIC_BASE_URL to your r2.dev or custom domain URL.
    # R2_PUBLIC_BASE_URL is accepted as a fallback alias.
    CLOUDFLARE_PUBLIC_BASE_URL: Optional[str] = None
    R2_PUBLIC_BASE_URL: Optional[str] = None          # legacy alias

    @property
    def public_base_url(self) -> Optional[str]:
        return self.CLOUDFLARE_PUBLIC_BASE_URL or self.R2_PUBLIC_BASE_URL

    # ── OpenAI (Image generation — gpt-image-1) ───────────────────────────────
    OPENAI_API_KEY: Optional[str] = None
    # Multiview fallback to OpenAI images.edit — OFF by default (burns credits)
    OPENAI_IMAGE_FALLBACK: bool = False

    # ── Google Gemini (image editing — multiview synthesis + photo enhance) ───
    # Preferred: Vertex AI via service account (project credits/billing).
    # Set GCP_PROJECT_ID + GOOGLE_APPLICATION_CREDENTIALS to enable; falls back
    # to AI Studio with GEMINI_API_KEY (free tier = NO image quota).
    GCP_PROJECT_ID: Optional[str] = None
    GCP_LOCATION: str = "global"          # image models are global-only on Vertex
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = None  # service-account JSON path
    GEMINI_API_KEY: Optional[str] = None
    # Nano Banana 2 Lite; override via env to swap models without a deploy
    GEMINI_IMAGE_MODEL: str = "gemini-3.1-flash-lite-image"

    @property
    def gemini_enabled(self) -> bool:
        return bool(self.GCP_PROJECT_ID or self.GEMINI_API_KEY)

    # ── RunPod ────────────────────────────────────────────────────────────────
    RUNPOD_API_KEY: str = ""
    RUNPOD_ENDPOINT_ID: str = ""                             # legacy video path
    RUNPOD_FLAME_ENDPOINT_ID: Optional[str] = None          # DECA flame_fit (current)
    RUNPOD_RECONSTRUCT_ENDPOINT_ID: Optional[str] = None    # Gaussian reconstruct (current)
    # Phase 2 — MICA identity + EMOCA detailed face reconstruction
    RUNPOD_MICA_ENDPOINT_ID: Optional[str] = None           # MICA multi-view identity (legacy)
    RUNPOD_LAM_ENDPOINT_ID: Optional[str] = None            # LAM one-shot gaussian head
    RUNPOD_EMOCA_ENDPOINT_ID: Optional[str] = None          # EMOCA detailed mesh + albedo

    MOCK_PIPELINE: bool = False

    # DEV_STORAGE=true writes to /tmp/avatar-dev/ and serves via /dev-storage/.
    # No R2 credentials needed. Never use in production.
    DEV_STORAGE: bool = False

    # ── Processing limits ─────────────────────────────────────────────────────
    MAX_VIDEO_SIZE_MB: int = 500
    MAX_AUDIO_SIZE_MB: int = 50
    MAX_PHOTO_SIZE_MB: int = 20

    # ── Optional extras (wired up later) ─────────────────────────────────────
    ELEVENLAB_API_KEY: Optional[str] = None
    ENABLE_RUNPOD: bool = False
    ENABLE_LOCAL_WORKER: bool = False
    RUNPOD_WEBHOOK_URL: Optional[str] = None

    class Config:
        # Accept .env from either the backend/ directory or the project root
        env_file = ("backend/.env", ".env")
        case_sensitive = True
        extra = "ignore"   # silently skip any unknown env vars


settings = Settings()
