from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import ValidationError

from app.models.caption_preset import (
    CaptionPresetExportPayload,
    CaptionPresetImportPayload,
    CaptionPresetImportResponse,
    CaptionPresetListResponse,
    CaptionPresetResponse,
    CreateCaptionPresetRequest,
    UpdateCaptionPresetRequest,
)
from app.services.caption_presets import (
    CaptionPresetConflictError,
    CaptionPresetNotFoundError,
    CaptionPresetValidationError,
    create_caption_preset,
    delete_caption_preset,
    duplicate_caption_preset,
    export_caption_preset,
    get_caption_preset,
    import_caption_presets,
    list_caption_presets,
    update_caption_preset,
)

router = APIRouter(prefix="/api/caption-presets", tags=["caption-presets"])


@router.get("", response_model=CaptionPresetListResponse)
def list_presets() -> CaptionPresetListResponse:
    return list_caption_presets()


@router.post("", response_model=CaptionPresetResponse, status_code=201)
def create_preset(request: CreateCaptionPresetRequest) -> CaptionPresetResponse:
    try:
        return create_caption_preset(request)
    except CaptionPresetValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/import", response_model=CaptionPresetImportResponse)
def import_presets(payload: CaptionPresetImportPayload) -> CaptionPresetImportResponse:
    try:
        imported = import_caption_presets(payload)
        return CaptionPresetImportResponse(imported=imported)
    except CaptionPresetValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/{preset_id}", response_model=CaptionPresetResponse)
def get_preset(preset_id: str) -> CaptionPresetResponse:
    try:
        return get_caption_preset(preset_id)
    except CaptionPresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc


@router.patch("/{preset_id}", response_model=CaptionPresetResponse)
def patch_preset(preset_id: str, request: UpdateCaptionPresetRequest) -> CaptionPresetResponse:
    try:
        return update_caption_preset(preset_id, request)
    except CaptionPresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except CaptionPresetConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    except CaptionPresetValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{preset_id}", status_code=204, response_class=Response)
def remove_preset(preset_id: str) -> Response:
    try:
        delete_caption_preset(preset_id)
    except CaptionPresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except CaptionPresetConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.message) from exc
    return Response(status_code=204)


@router.post("/{preset_id}/duplicate", response_model=CaptionPresetResponse, status_code=201)
def duplicate_preset(preset_id: str) -> CaptionPresetResponse:
    try:
        return duplicate_caption_preset(preset_id)
    except CaptionPresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
    except CaptionPresetValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc


@router.get("/{preset_id}/export", response_model=CaptionPresetExportPayload)
def export_preset(preset_id: str) -> CaptionPresetExportPayload:
    try:
        return export_caption_preset(preset_id)
    except CaptionPresetNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.message) from exc
