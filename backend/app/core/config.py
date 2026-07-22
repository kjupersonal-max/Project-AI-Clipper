from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Project AI Clipper API"
    cors_origins: list[str] = ["http://localhost:3000"]
    upload_dir: Path = BACKEND_ROOT / "uploads"
    processed_dir: Path = BACKEND_ROOT / "processed"
    audio_dir: Path = BACKEND_ROOT / "audio"
    transcripts_dir: Path = BACKEND_ROOT / "transcripts"
    max_upload_size_bytes: int = 5 * 1024 * 1024 * 1024  # 5 GB
    allowed_extensions: set[str] = {".mp4", ".mov", ".mkv", ".webm"}
    chunk_size_bytes: int = 1024 * 1024  # 1 MB
    project_metadata_filename: str = "project.json"
    ffprobe_timeout_seconds: int = 120
    ffmpeg_timeout_seconds: int = 600
    audio_output_filename: str = "audio.wav"
    transcript_output_filename: str = "transcript.json"
    whisper_model_size: str = "base"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"


settings = Settings()
