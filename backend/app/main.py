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

app.include_router(avatar.router, prefix=settings.API_V1_PREFIX)
app.include_router(animate.router, prefix=settings.API_V1_PREFIX)
app.include_router(stream.router, prefix=settings.API_V1_PREFIX)
app.include_router(speak.router, prefix=settings.API_V1_PREFIX)

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
