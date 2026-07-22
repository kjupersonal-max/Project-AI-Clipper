from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
    )

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
    analysis_dir: Path = BACKEND_ROOT / "analysis"
    analysis_output_filename: str = "analysis.json"
    analysis_provider: str = "auto"
    analysis_external_provider: str = "openai"
    analysis_model: str = "gpt-4o-mini"
    analysis_api_key: str = ""
    analysis_api_base_url: str | None = None
    analysis_batch_size: int = 10
    analysis_timeout_seconds: int = 120
    analysis_max_transcript_chars: int = 12000
    analysis_context_segments: int = 2
    analysis_max_retries: int = 2
    clip_candidates_dir: Path = BACKEND_ROOT / "clip_candidates"
    clip_candidates_output_filename: str = "clip_candidates.json"
    clip_selection_min_duration_seconds: float = 15.0
    clip_selection_max_duration_seconds: float = 60.0
    clip_selection_max_gap_seconds: float = 2.5
    clip_selection_max_candidates: int = 10
    clip_selection_min_score: float = 35.0
    clip_export_max_duration_seconds: float = 120.0
    clip_export_subdir: str = "clips"
    clip_exports_manifest_filename: str = "exports.json"
    clip_export_timeout_seconds: int = 600


settings = Settings()
