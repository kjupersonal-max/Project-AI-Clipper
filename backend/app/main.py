from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.projects import router as projects_router
from app.api.routes.uploads import router as uploads_router
from app.core.config import settings
from app.services.project_store import ensure_backend_dirs
from app.services.video_processing import check_ffmpeg_availability, resolve_ffmpeg_executables

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(uploads_router)
app.include_router(projects_router)


@app.on_event("startup")
def on_startup() -> None:
    ensure_backend_dirs()
    ffmpeg_path, ffprobe_path = resolve_ffmpeg_executables()
    print(f"Resolved FFmpeg executable: {ffmpeg_path or 'not found'}")
    print(f"Resolved FFprobe executable: {ffprobe_path or 'not found'}")
    availability = check_ffmpeg_availability()
    if not availability.ffmpeg_available or not availability.ffprobe_available:
        print(f"WARNING: FFmpeg tooling unavailable: {availability.error}")


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "healthy"}
