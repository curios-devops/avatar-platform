from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import settings
from .api import avatar, animate, stream, speak

app = FastAPI(title=settings.PROJECT_NAME)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# speak first: its literal routes (/avatar/voices) must win over
# avatar.py's catch-all GET /avatar/{avatar_id} (FastAPI matches in order)
app.include_router(speak.router, prefix=settings.API_V1_PREFIX)
app.include_router(avatar.router, prefix=settings.API_V1_PREFIX)
app.include_router(animate.router, prefix=settings.API_V1_PREFIX)
app.include_router(stream.router, prefix=settings.API_V1_PREFIX)

@app.on_event("startup")
async def _sync_lam_idle_timeout() -> None:
    """Push LAM_IDLE_TIMEOUT_S from .env to the RunPod endpoint (best-effort),
    so the warm-window knob lives in config instead of the RunPod console."""
    if not (settings.RUNPOD_LAM_ENDPOINT_ID and settings.RUNPOD_API_KEY):
        return
    import logging

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.patch(
                f"https://rest.runpod.io/v1/endpoints/{settings.RUNPOD_LAM_ENDPOINT_ID}",
                json={"idleTimeout": settings.LAM_IDLE_TIMEOUT_S},
                headers={"Authorization": f"Bearer {settings.RUNPOD_API_KEY}"},
            )
            r.raise_for_status()
        logging.getLogger(__name__).info(
            "LAM endpoint idleTimeout synced to %ss", settings.LAM_IDLE_TIMEOUT_S
        )
    except Exception as exc:
        logging.getLogger(__name__).warning("LAM idleTimeout sync failed: %s", exc)


# Dev-only: serve local artifact files at /dev-storage/
if settings.DEV_STORAGE:
    import pathlib
    dev_root = pathlib.Path("/tmp/avatar-dev")
    dev_root.mkdir(parents=True, exist_ok=True)
    app.mount("/dev-storage", StaticFiles(directory=str(dev_root)), name="dev-storage")


@app.get("/")
async def root():
    return {"name": settings.PROJECT_NAME, "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}
