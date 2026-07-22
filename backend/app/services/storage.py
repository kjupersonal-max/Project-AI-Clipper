import re
import shutil
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from starlette.requests import ClientDisconnect

from app.core.config import settings


class FilenameError(ValueError):
    pass


def generate_project_id() -> str:
    return str(uuid.uuid4())


def get_extension(filename: str) -> str:
    return Path(filename).suffix.lower()


def validate_extension(filename: str) -> str:
    extension = get_extension(filename)
    if extension not in settings.allowed_extensions:
        allowed = ", ".join(sorted(settings.allowed_extensions))
        raise FilenameError(
            f"Unsupported file type '{extension or 'unknown'}'. Allowed: {allowed}"
        )
    return extension


def sanitize_filename(filename: str) -> str:
    basename = Path(filename).name
    if not basename or basename in {".", ".."}:
        raise FilenameError("Invalid filename.")

    extension = validate_extension(basename)
    stem = Path(basename).stem

    safe_stem = re.sub(r"[^\w.\- ]+", "", stem, flags=re.UNICODE)
    safe_stem = re.sub(r"\s+", "_", safe_stem.strip("._ "))
    safe_stem = safe_stem[:200] or "upload"

    return f"{safe_stem}{extension}"


def ensure_upload_root() -> Path:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    return settings.upload_dir


def cleanup_project_dir(project_dir: Path) -> None:
    if project_dir.exists():
        shutil.rmtree(project_dir, ignore_errors=True)


async def stream_upload_to_disk(
    upload_file: UploadFile,
    *,
    original_filename: str,
    project_id: str,
) -> tuple[str, str, int]:
    upload_root = ensure_upload_root()
    project_dir = upload_root / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    sanitized_filename = sanitize_filename(original_filename)
    destination = project_dir / sanitized_filename

    if destination.exists():
        cleanup_project_dir(project_dir)
        raise HTTPException(status_code=409, detail="Upload conflict. Please retry.")

    size_bytes = 0

    try:
        with destination.open("wb") as buffer:
            while True:
                chunk = await upload_file.read(settings.chunk_size_bytes)
                if not chunk:
                    break

                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_size_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"File exceeds maximum upload size of "
                            f"{settings.max_upload_size_bytes // (1024 * 1024 * 1024)} GB."
                        ),
                    )

                buffer.write(chunk)
    except ClientDisconnect:
        cleanup_project_dir(project_dir)
        raise HTTPException(status_code=499, detail="Upload cancelled by client.")
    except HTTPException:
        cleanup_project_dir(project_dir)
        raise
    except Exception as exc:
        cleanup_project_dir(project_dir)
        raise HTTPException(
            status_code=500,
            detail="Failed to save upload. Please try again.",
        ) from exc
    finally:
        await upload_file.close()

    if size_bytes == 0:
        cleanup_project_dir(project_dir)
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    relative_path = f"{project_id}/{sanitized_filename}"
    return original_filename, relative_path, size_bytes
