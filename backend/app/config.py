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

    # ── Interruptor global de Google ──────────────────────────────────────────
    # false apaga TODO lo que pasa por Google (Gemini LLM, visión, Nano Banana,
    # Vertex). Con la facturación de vuelta basta con poner true en .env.
    GOOGLE_ENABLED: bool = True

    # ── Generación de imagen (Imagine: texto → retrato) ───────────────────────
    # openai | pruna | nanobanana. Si el elegido no está configurado (o Google
    # está apagado) se usa el siguiente disponible en ese mismo orden.
    IMAGE_GEN_PROVIDER: str = "openai"
    IMAGE_GEN_FALLBACK: str = "pruna"
    # Regla Twin de MEYA: una foto o vídeo de una persona real solo se procesa
    # si quien lo sube declara que es suyo. Imagine (personaje inventado) no lo necesita.
    REQUIRE_LIKENESS_CONSENT: bool = True
    OPENAI_IMAGE_MODEL: str = "gpt-image-2"
    PRUNA_API_KEY: Optional[str] = None
    PRUNA_IMAGE_MODEL: str = "p-image"

    # ── OpenAI ────────────────────────────────────────────────────────────────
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
    # Vision model — photo intake analysis (framing head/half/full).
    # 2.5-flash chosen over 3.1-flash-lite: the lite model misclassifies
    # head-and-shoulders portraits as "half" (tested 2026-07-17).
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"

    @property
    def gemini_enabled(self) -> bool:
        return self.GOOGLE_ENABLED and bool(self.GCP_PROJECT_ID or self.GEMINI_API_KEY)

    # ── RunPod ────────────────────────────────────────────────────────────────
    RUNPOD_API_KEY: str = ""
    RUNPOD_ENDPOINT_ID: str = ""                             # legacy video path
    RUNPOD_FLAME_ENDPOINT_ID: Optional[str] = None          # DECA flame_fit (current)
    RUNPOD_RECONSTRUCT_ENDPOINT_ID: Optional[str] = None    # Gaussian reconstruct (current)
    # Phase 2 — MICA identity + EMOCA detailed face reconstruction
    RUNPOD_MICA_ENDPOINT_ID: Optional[str] = None           # MICA multi-view identity (legacy)
    RUNPOD_LAM_ENDPOINT_ID: Optional[str] = None            # LAM one-shot gaussian head (tier 1)
    RUNPOD_LHM_ENDPOINT_ID: Optional[str] = None            # LHM half/full-body gaussian (tiers 2-3)
    RUNPOD_MUSETALK_ENDPOINT_ID: Optional[str] = None       # A2 lip-sync serverless (etapa A)
    RUNPOD_EMOCA_ENDPOINT_ID: Optional[str] = None          # EMOCA detailed mesh + albedo
    # Seconds a LAM worker stays warm (billed) after its last job. Synced to
    # the RunPod endpoint at backend startup — .env is the source of truth.
    LAM_IDLE_TIMEOUT_S: int = 300

    MOCK_PIPELINE: bool = False
    # Pipeline de cabeza legacy (multiview + MICA/CPU). Solo para QA: da caras
    # deformadas, por eso sin LAM el job falla salvo que esto esté en true.
    LEGACY_HEAD_PIPELINE: bool = False

    # DEV_STORAGE=true writes to /tmp/avatar-dev/ and serves via /dev-storage/.
    # No R2 credentials needed. Never use in production.
    DEV_STORAGE: bool = False

    # ── Processing limits ─────────────────────────────────────────────────────
    MAX_VIDEO_SIZE_MB: int = 500
    MAX_AUDIO_SIZE_MB: int = 50
    MAX_PHOTO_SIZE_MB: int = 20

    # ── ETAPA A: orquestador conversacional (docs/nueva_arquitectura.md) ──────
    # Primario + fallback intercambiables por env. Medido 2026-07-19 (TTFT):
    # gemini-3.1-flash-lite ~880ms ≈ gpt-4o-mini ~900-1200ms;
    # gemini-2.5-flash/lite ~11s por el express (thinking) — NO usar en chat.
    ORCH_LLM_PRIMARY: str = "gemini"           # gemini | openai
    ORCH_LLM_FALLBACK: str = "openai"
    ORCH_FIRST_TOKEN_TIMEOUT_S: float = 4.0    # si el primario no arranca, conmutar
    ORCH_OPENAI_MODEL: str = "gpt-4o-mini"
    ORCH_GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    ORCH_WHISPER_MODEL: str = "base"           # faster-whisper: tiny|base|small…
    # Persona del avatar (clon digital) — None usa el prompt por defecto
    ORCH_SYSTEM_PROMPT: Optional[str] = None
    # Voz del chat: orden de proveedores. ElevenLabs primero (visemas reales);
    # si falla, OpenAI TTS con visemas estimados. Tras un fallo, ElevenLabs se
    # salta durante ORCH_TTS_COOLDOWN_S para no pagar su latencia en cada frase.
    ORCH_TTS_PROVIDERS: str = "elevenlabs,openai"
    ORCH_TTS_COOLDOWN_S: float = 120.0
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_TTS_VOICE: str = "coral"

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
