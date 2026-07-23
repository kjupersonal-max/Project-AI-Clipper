from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.project import (
    CaptionAnimationType,
    CaptionSafeAreaMode,
    CaptionStyle,
    CaptionStylePresetId,
    CaptionTextAlignment,
    CaptionTextTransform,
    CaptionWordsPerGroup,
    utc_now_iso,
)

CAPTION_PRESET_SCHEMA_VERSION = 1


class CaptionPresetStyle(BaseModel):
    font_family: str = "Arial, Helvetica, sans-serif"
    font_size: float = Field(default=22.0, ge=12.0, le=72.0)
    font_weight: int = Field(default=600, ge=100, le=900)
    text_color: str = "#FFFFFF"
    active_word_color: str = "#FFFFFF"
    outline_color: str = "#000000"
    outline_width: float = Field(default=1.0, ge=0.0, le=8.0)
    background_color: str = "#000000"
    background_opacity: float = Field(default=0.45, ge=0.0, le=1.0)
    shadow_enabled: bool = False
    shadow_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    text_alignment: CaptionTextAlignment = CaptionTextAlignment.CENTER
    horizontal_position: float = Field(default=50.0, ge=0.0, le=100.0)
    vertical_position: float = Field(default=88.0, ge=0.0, le=100.0)
    max_line_width: float = Field(default=85.0, ge=50.0, le=100.0)
    words_per_group: CaptionWordsPerGroup = CaptionWordsPerGroup.FULL
    text_transform: CaptionTextTransform = CaptionTextTransform.NONE
    animation_type: CaptionAnimationType = CaptionAnimationType.FADE
    animation_intensity: float = Field(default=0.4, ge=0.0, le=1.0)
    safe_area_mode: CaptionSafeAreaMode = CaptionSafeAreaMode.NONE


class CaptionPresetRecord(BaseModel):
    id: str
    name: str
    is_builtin: bool = False
    style: CaptionPresetStyle
    created_at: str = Field(default_factory=utc_now_iso)
    updated_at: str = Field(default_factory=utc_now_iso)


class CaptionPresetResponse(BaseModel):
    id: str
    name: str
    is_builtin: bool
    is_default: bool
    style: CaptionPresetStyle
    created_at: str
    updated_at: str


class CaptionPresetListResponse(BaseModel):
    presets: list[CaptionPresetResponse] = Field(default_factory=list)
    default_preset_id: str | None = None


class CreateCaptionPresetRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    style: CaptionPresetStyle


class UpdateCaptionPresetRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    style: CaptionPresetStyle | None = None
    is_default: bool | None = None


class CaptionPresetExportPayload(BaseModel):
    schema_version: int = CAPTION_PRESET_SCHEMA_VERSION
    preset: CaptionPresetExportItem


class CaptionPresetExportItem(BaseModel):
    name: str
    style: CaptionPresetStyle


class CaptionPresetBulkExportPayload(BaseModel):
    schema_version: int = CAPTION_PRESET_SCHEMA_VERSION
    presets: list[CaptionPresetExportItem] = Field(min_length=1)


class CaptionPresetImportPayload(BaseModel):
    schema_version: int
    preset: CaptionPresetExportItem | None = None
    presets: list[CaptionPresetExportItem] | None = None


class CaptionPresetImportResponse(BaseModel):
    imported: list[CaptionPresetResponse] = Field(default_factory=list)


def caption_preset_style_to_caption_style(style: CaptionPresetStyle) -> CaptionStyle:
    return CaptionStyle(
        preset_id=CaptionStylePresetId.CUSTOM,
        **style.model_dump(),
    )


def caption_style_to_preset_style(style: CaptionStyle) -> CaptionPresetStyle:
    payload = style.model_dump()
    payload.pop("preset_id", None)
    return CaptionPresetStyle.model_validate(payload)
