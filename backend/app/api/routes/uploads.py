from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from app.services.project_store import create_project_metadata
from app.services.storage import (
    FilenameError,
    generate_project_id,
    stream_upload_to_disk,
    validate_extension,
)

router = APIRouter(prefix="/api/uploads", tags=["uploads"])


class UploadResponse(BaseModel):
    project_id: str
    filename: str
    stored_path: str
    size_bytes: int
    status: str


@router.post("", response_model=UploadResponse, status_code=201)
async def upload_video(file: UploadFile = File(...)) -> UploadResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="A filename is required.")

    try:
        validate_extension(file.filename)
        project_id = generate_project_id()
        original_filename, stored_path, size_bytes = await stream_upload_to_disk(
            file,
            original_filename=file.filename,
            project_id=project_id,
        )
    except FilenameError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    create_project_metadata(
        project_id=project_id,
        original_filename=original_filename,
        stored_video_path=stored_path,
        size_bytes=size_bytes,
    )

    return UploadResponse(
        project_id=project_id,
        filename=original_filename,
        stored_path=stored_path,
        size_bytes=size_bytes,
        status="uploaded",
    )
