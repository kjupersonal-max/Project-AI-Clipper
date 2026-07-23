from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings
from app.models.caption_preset import (
    CAPTION_PRESET_SCHEMA_VERSION,
    CaptionPresetExportItem,
    CaptionPresetExportPayload,
    CaptionPresetImportPayload,
    CaptionPresetListResponse,
    CaptionPresetRecord,
    CaptionPresetResponse,
    CaptionPresetStyle,
    CreateCaptionPresetRequest,
    UpdateCaptionPresetRequest,
    caption_preset_style_to_caption_style,
    caption_style_to_preset_style,
    utc_now_iso,
)
from app.models.project import (
    CaptionAnimationType,
    CaptionSafeAreaMode,
    CaptionStyle,
    CaptionTextAlignment,
    CaptionTextTransform,
    CaptionWordsPerGroup,
)

HEX_COLOR_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}$")

BUILTIN_PRESET_DEFINITIONS: list[tuple[str, str, CaptionPresetStyle]] = [
    (
        "tiktok-classic",
        "TikTok Classic",
        CaptionPresetStyle(
            font_family="Arial, Helvetica, sans-serif",
            font_size=28,
            font_weight=700,
            text_color="#FFFFFF",
            active_word_color="#FFFFFF",
            outline_color="#000000",
            outline_width=2.5,
            background_color="#000000",
            background_opacity=0.0,
            shadow_enabled=True,
            shadow_strength=0.5,
            text_alignment=CaptionTextAlignment.CENTER,
            horizontal_position=50,
            vertical_position=82,
            max_line_width=90,
            words_per_group=CaptionWordsPerGroup.TWO,
            text_transform=CaptionTextTransform.NONE,
            animation_type=CaptionAnimationType.POP,
            animation_intensity=0.65,
            safe_area_mode=CaptionSafeAreaMode.TIKTOK,
        ),
    ),
    (
        "bold-yellow",
        "Bold Yellow",
        CaptionPresetStyle(
            font_family="Impact, Haettenschweiler, sans-serif",
            font_size=34,
            font_weight=800,
            text_color="#FFFF00",
            active_word_color="#FFFFFF",
            outline_color="#000000",
            outline_width=3.5,
            background_color="#000000",
            background_opacity=0.2,
            shadow_enabled=True,
            shadow_strength=0.6,
            text_alignment=CaptionTextAlignment.CENTER,
            horizontal_position=50,
            vertical_position=78,
            max_line_width=92,
            words_per_group=CaptionWordsPerGroup.TWO,
            text_transform=CaptionTextTransform.UPPERCASE,
            animation_type=CaptionAnimationType.POP,
            animation_intensity=0.75,
            safe_area_mode=CaptionSafeAreaMode.NONE,
        ),
    ),
    (
        "minimal-clean",
        "Minimal Clean",
        CaptionPresetStyle(
            font_family="Arial, Helvetica, sans-serif",
            font_size=22,
            font_weight=600,
            text_color="#FFFFFF",
            active_word_color="#FFFFFF",
            outline_color="#000000",
            outline_width=1.0,
            background_color="#000000",
            background_opacity=0.45,
            shadow_enabled=False,
            shadow_strength=0.0,
            text_alignment=CaptionTextAlignment.CENTER,
            horizontal_position=50,
            vertical_position=88,
            max_line_width=85,
            words_per_group=CaptionWordsPerGroup.FULL,
            text_transform=CaptionTextTransform.NONE,
            animation_type=CaptionAnimationType.FADE,
            animation_intensity=0.4,
            safe_area_mode=CaptionSafeAreaMode.NONE,
        ),
    ),
    (
        "podcast",
        "Podcast",
        CaptionPresetStyle(
            font_family="Georgia, serif",
            font_size=20,
            font_weight=500,
            text_color="#F5F5F5",
            active_word_color="#F5F5F5",
            outline_color="#1A1A1A",
            outline_width=0.0,
            background_color="#1A1A1A",
            background_opacity=0.75,
            shadow_enabled=False,
            shadow_strength=0.0,
            text_alignment=CaptionTextAlignment.LEFT,
            horizontal_position=50,
            vertical_position=85,
            max_line_width=88,
            words_per_group=CaptionWordsPerGroup.FULL,
            text_transform=CaptionTextTransform.NONE,
            animation_type=CaptionAnimationType.FADE,
            animation_intensity=0.3,
            safe_area_mode=CaptionSafeAreaMode.NONE,
        ),
    ),
    (
        "gaming",
        "Gaming",
        CaptionPresetStyle(
            font_family="Impact, Haettenschweiler, sans-serif",
            font_size=30,
            font_weight=800,
            text_color="#E0E0E0",
            active_word_color="#39FF14",
            outline_color="#000000",
            outline_width=3.0,
            background_color="#000000",
            background_opacity=0.35,
            shadow_enabled=True,
            shadow_strength=0.55,
            text_alignment=CaptionTextAlignment.CENTER,
            horizontal_position=50,
            vertical_position=80,
            max_line_width=90,
            words_per_group=CaptionWordsPerGroup.THREE,
            text_transform=CaptionTextTransform.UPPERCASE,
            animation_type=CaptionAnimationType.ACTIVE_WORD_EMPHASIS,
            animation_intensity=0.85,
            safe_area_mode=CaptionSafeAreaMode.NONE,
        ),
    ),
    (
        "high-contrast",
        "High Contrast",
        CaptionPresetStyle(
            font_family="Arial, Helvetica, sans-serif",
            font_size=26,
            font_weight=800,
            text_color="#FFFF00",
            active_word_color="#FFFFFF",
            outline_color="#000000",
            outline_width=4.0,
            background_color="#000000",
            background_opacity=0.85,
            shadow_enabled=True,
            shadow_strength=0.6,
            text_alignment=CaptionTextAlignment.CENTER,
            horizontal_position=50,
            vertical_position=85,
            max_line_width=90,
            words_per_group=CaptionWordsPerGroup.FULL,
            text_transform=CaptionTextTransform.UPPERCASE,
            animation_type=CaptionAnimationType.NONE,
            animation_intensity=0.5,
            safe_area_mode=CaptionSafeAreaMode.NONE,
        ),
    ),
]

BUILTIN_PRESET_IDS = {preset_id for preset_id, _, _ in BUILTIN_PRESET_DEFINITIONS}
DEFAULT_BUILTIN_PRESET_ID = "minimal-clean"


class CaptionPresetValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptionPresetNotFoundError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptionPresetConflictError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class CaptionPresetStore(BaseModel):
    default_preset_id: str | None = DEFAULT_BUILTIN_PRESET_ID
    custom_presets: list[CaptionPresetRecord] = Field(default_factory=list)


def get_caption_presets_dir() -> Path:
    presets_dir = settings.processed_dir / settings.caption_presets_subdir
    presets_dir.mkdir(parents=True, exist_ok=True)
    return presets_dir


def get_caption_presets_store_path() -> Path:
    return get_caption_presets_dir() / settings.caption_presets_store_filename


def _validate_style_colors(style: CaptionPresetStyle) -> None:
    for field_name in ("text_color", "active_word_color", "outline_color", "background_color"):
        value = getattr(style, field_name)
        if not HEX_COLOR_PATTERN.match(value):
            raise CaptionPresetValidationError(
                f"Invalid color for {field_name}: expected #RRGGBB hex."
            )


def _validate_preset_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise CaptionPresetValidationError("Preset name cannot be empty.")
    return cleaned


def _load_store() -> CaptionPresetStore:
    path = get_caption_presets_store_path()
    if not path.exists():
        return CaptionPresetStore()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return CaptionPresetStore.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise CaptionPresetValidationError("Caption preset storage is corrupted.") from exc


def _write_store(store: CaptionPresetStore) -> None:
    path = get_caption_presets_store_path()
    temp_path = path.with_suffix(".json.part")
    temp_path.write_text(
        json.dumps(store.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def _builtin_records() -> list[CaptionPresetRecord]:
    return [
        CaptionPresetRecord(
            id=preset_id,
            name=name,
            is_builtin=True,
            style=style,
            created_at="1970-01-01T00:00:00+00:00",
            updated_at="1970-01-01T00:00:00+00:00",
        )
        for preset_id, name, style in BUILTIN_PRESET_DEFINITIONS
    ]


def _resolve_default_preset_id(store: CaptionPresetStore) -> str:
    if store.default_preset_id and (
        store.default_preset_id in BUILTIN_PRESET_IDS
        or any(item.id == store.default_preset_id for item in store.custom_presets)
    ):
        return store.default_preset_id
    return DEFAULT_BUILTIN_PRESET_ID


def _to_response(record: CaptionPresetRecord, *, is_default: bool) -> CaptionPresetResponse:
    return CaptionPresetResponse(
        id=record.id,
        name=record.name,
        is_builtin=record.is_builtin,
        is_default=is_default,
        style=record.style,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _get_record_by_id(store: CaptionPresetStore, preset_id: str) -> CaptionPresetRecord:
    if preset_id in BUILTIN_PRESET_IDS:
        for record in _builtin_records():
            if record.id == preset_id:
                return record
    for record in store.custom_presets:
        if record.id == preset_id:
            return record
    raise CaptionPresetNotFoundError(f"Caption preset not found: {preset_id}")


def _existing_names(store: CaptionPresetStore, *, exclude_id: str | None = None) -> set[str]:
    names = {record.name.casefold() for record in _builtin_records()}
    for record in store.custom_presets:
        if exclude_id is None or record.id != exclude_id:
            names.add(record.name.casefold())
    return names


def _disambiguate_name(base_name: str, taken: set[str]) -> str:
    cleaned = _validate_preset_name(base_name)
    if cleaned.casefold() not in taken:
        return cleaned
    index = 2
    while f"{cleaned} ({index})".casefold() in taken:
        index += 1
    return f"{cleaned} ({index})"


def list_caption_presets() -> CaptionPresetListResponse:
    store = _load_store()
    default_id = _resolve_default_preset_id(store)
    presets = [
        _to_response(record, is_default=record.id == default_id)
        for record in _builtin_records() + store.custom_presets
    ]
    return CaptionPresetListResponse(presets=presets, default_preset_id=default_id)


def get_caption_preset(preset_id: str) -> CaptionPresetResponse:
    store = _load_store()
    default_id = _resolve_default_preset_id(store)
    record = _get_record_by_id(store, preset_id)
    return _to_response(record, is_default=record.id == default_id)


def create_caption_preset(request: CreateCaptionPresetRequest) -> CaptionPresetResponse:
    store = _load_store()
    default_id = _resolve_default_preset_id(store)
    _validate_style_colors(request.style)
    name = _disambiguate_name(request.name, _existing_names(store))
    now = utc_now_iso()
    record = CaptionPresetRecord(
        id=str(uuid.uuid4()),
        name=name,
        is_builtin=False,
        style=request.style,
        created_at=now,
        updated_at=now,
    )
    store.custom_presets.append(record)
    _write_store(store)
    return _to_response(record, is_default=record.id == default_id)


def update_caption_preset(
    preset_id: str,
    request: UpdateCaptionPresetRequest,
) -> CaptionPresetResponse:
    if preset_id in BUILTIN_PRESET_IDS:
        raise CaptionPresetConflictError("Built-in presets cannot be modified.")

    store = _load_store()
    index = next(
        (idx for idx, item in enumerate(store.custom_presets) if item.id == preset_id),
        None,
    )
    if index is None:
        raise CaptionPresetNotFoundError(f"Caption preset not found: {preset_id}")

    record = store.custom_presets[index]

    if request.name is not None:
        cleaned = _validate_preset_name(request.name)
        taken = _existing_names(store, exclude_id=preset_id)
        if cleaned.casefold() in taken:
            raise CaptionPresetConflictError(f"A preset named '{cleaned}' already exists.")
        record = record.model_copy(update={"name": cleaned})

    if request.style is not None:
        _validate_style_colors(request.style)
        record = record.model_copy(update={"style": request.style})

    if request.is_default is True:
        store.default_preset_id = preset_id
    elif request.is_default is False and store.default_preset_id == preset_id:
        store.default_preset_id = DEFAULT_BUILTIN_PRESET_ID

    record = record.model_copy(update={"updated_at": utc_now_iso()})
    store.custom_presets[index] = record
    _write_store(store)
    default_id = _resolve_default_preset_id(store)
    return _to_response(record, is_default=record.id == default_id)


def delete_caption_preset(preset_id: str) -> None:
    store = _load_store()
    if preset_id in BUILTIN_PRESET_IDS:
        raise CaptionPresetConflictError("Built-in presets cannot be deleted.")

    remaining = [item for item in store.custom_presets if item.id != preset_id]
    if len(remaining) == len(store.custom_presets):
        raise CaptionPresetNotFoundError(f"Caption preset not found: {preset_id}")

    store.custom_presets = remaining
    if store.default_preset_id == preset_id:
        store.default_preset_id = DEFAULT_BUILTIN_PRESET_ID
    _write_store(store)


def duplicate_caption_preset(preset_id: str, *, name: str | None = None) -> CaptionPresetResponse:
    store = _load_store()
    source = _get_record_by_id(store, preset_id)
    requested_name = name or f"{source.name} Copy"
    return create_caption_preset(
        CreateCaptionPresetRequest(name=requested_name, style=source.style.model_copy(deep=True))
    )


def export_caption_preset(preset_id: str) -> CaptionPresetExportPayload:
    preset = get_caption_preset(preset_id)
    return CaptionPresetExportPayload(
        preset=CaptionPresetExportItem(name=preset.name, style=preset.style)
    )


def import_caption_presets(payload: CaptionPresetImportPayload) -> list[CaptionPresetResponse]:
    if payload.schema_version != CAPTION_PRESET_SCHEMA_VERSION:
        raise CaptionPresetValidationError(
            f"Unsupported preset schema version: {payload.schema_version}."
        )

    items: list[CaptionPresetExportItem] = []
    if payload.preset is not None:
        items.append(payload.preset)
    if payload.presets:
        items.extend(payload.presets)
    if not items:
        raise CaptionPresetValidationError("Import payload must include at least one preset.")

    imported: list[CaptionPresetResponse] = []
    for item in items:
        _validate_style_colors(item.style)
        imported.append(
            create_caption_preset(
                CreateCaptionPresetRequest(name=item.name, style=item.style)
            )
        )
    return imported


def get_default_caption_style() -> CaptionStyle:
    store = _load_store()
    preset_id = _resolve_default_preset_id(store)
    record = _get_record_by_id(store, preset_id)
    return caption_preset_style_to_caption_style(record.style)


def preset_style_from_caption_style(style: CaptionStyle) -> CaptionPresetStyle:
    return caption_style_to_preset_style(style)
