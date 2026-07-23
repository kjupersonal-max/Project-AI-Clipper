from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.caption_preset import (
    CAPTION_PRESET_SCHEMA_VERSION,
    CaptionPresetStyle,
    CreateCaptionPresetRequest,
)
from app.models.project import CaptionWordsPerGroup
from app.services.caption_presets import (
    BUILTIN_PRESET_IDS,
    DEFAULT_BUILTIN_PRESET_ID,
    create_caption_preset,
    get_caption_presets_store_path,
    list_caption_presets,
)
from app.services.clip_captions import generate_clip_captions


@pytest.fixture()
def preset_client():
    return TestClient(app)


def _custom_style(**overrides) -> CaptionPresetStyle:
    base = CaptionPresetStyle()
    return base.model_copy(update=overrides)


def test_list_includes_builtin_presets(preset_client, temp_backend_dirs):
    response = preset_client.get("/api/caption-presets")
    assert response.status_code == 200
    body = response.json()
    assert body["default_preset_id"] == DEFAULT_BUILTIN_PRESET_ID
    preset_ids = {item["id"] for item in body["presets"]}
    assert BUILTIN_PRESET_IDS.issubset(preset_ids)
    builtins = [item for item in body["presets"] if item["is_builtin"]]
    assert len(builtins) == len(BUILTIN_PRESET_IDS)
    assert all(item["name"] for item in builtins)


def test_create_custom_preset(preset_client, temp_backend_dirs):
    response = preset_client.post(
        "/api/caption-presets",
        json={
            "name": "My Studio Look",
            "style": _custom_style(text_color="#ABCDEF").model_dump(mode="json"),
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Studio Look"
    assert body["is_builtin"] is False
    assert body["is_default"] is False
    assert body["style"]["text_color"] == "#ABCDEF"


def test_duplicate_name_disambiguated_on_create(preset_client, temp_backend_dirs):
    payload = {
        "name": "Shared Name",
        "style": _custom_style().model_dump(mode="json"),
    }
    first = preset_client.post("/api/caption-presets", json=payload)
    second = preset_client.post("/api/caption-presets", json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["name"] == "Shared Name"
    assert second.json()["name"] == "Shared Name (2)"


def test_rename_custom_preset(preset_client, temp_backend_dirs):
    created = preset_client.post(
        "/api/caption-presets",
        json={"name": "Rename Me", "style": _custom_style().model_dump(mode="json")},
    ).json()
    response = preset_client.patch(
        f"/api/caption-presets/{created['id']}",
        json={"name": "Renamed"},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


def test_update_custom_preset_style(preset_client, temp_backend_dirs):
    created = preset_client.post(
        "/api/caption-presets",
        json={"name": "Styled", "style": _custom_style().model_dump(mode="json")},
    ).json()
    response = preset_client.patch(
        f"/api/caption-presets/{created['id']}",
        json={"style": _custom_style(words_per_group="1").model_dump(mode="json")},
    )
    assert response.status_code == 200
    assert response.json()["style"]["words_per_group"] == "1"


def test_delete_custom_preset(preset_client, temp_backend_dirs):
    created = preset_client.post(
        "/api/caption-presets",
        json={"name": "Delete Me", "style": _custom_style().model_dump(mode="json")},
    ).json()
    response = preset_client.delete(f"/api/caption-presets/{created['id']}")
    assert response.status_code == 204
    missing = preset_client.get(f"/api/caption-presets/{created['id']}")
    assert missing.status_code == 404


def test_prevent_builtin_deletion(preset_client, temp_backend_dirs):
    response = preset_client.delete("/api/caption-presets/minimal-clean")
    assert response.status_code == 409


def test_prevent_builtin_update(preset_client, temp_backend_dirs):
    response = preset_client.patch(
        "/api/caption-presets/minimal-clean",
        json={"name": "Nope"},
    )
    assert response.status_code == 409


def test_duplicate_builtin_preset(preset_client, temp_backend_dirs):
    response = preset_client.post("/api/caption-presets/gaming/duplicate")
    assert response.status_code == 201
    body = response.json()
    assert body["is_builtin"] is False
    assert body["name"].startswith("Gaming")
    assert body["style"]["active_word_color"] == "#39FF14"


def test_set_default_preset(preset_client, temp_backend_dirs):
    created = preset_client.post(
        "/api/caption-presets",
        json={"name": "Default Candidate", "style": _custom_style().model_dump(mode="json")},
    ).json()
    response = preset_client.patch(
        f"/api/caption-presets/{created['id']}",
        json={"is_default": True},
    )
    assert response.status_code == 200
    assert response.json()["is_default"] is True

    listed = preset_client.get("/api/caption-presets").json()
    assert listed["default_preset_id"] == created["id"]
    defaults = [item for item in listed["presets"] if item["is_default"]]
    assert len(defaults) == 1


def test_only_one_default_at_a_time(preset_client, temp_backend_dirs):
    first = preset_client.post(
        "/api/caption-presets",
        json={"name": "First Default", "style": _custom_style().model_dump(mode="json")},
    ).json()
    second = preset_client.post(
        "/api/caption-presets",
        json={"name": "Second Default", "style": _custom_style().model_dump(mode="json")},
    ).json()
    preset_client.patch(f"/api/caption-presets/{first['id']}", json={"is_default": True})
    preset_client.patch(f"/api/caption-presets/{second['id']}", json={"is_default": True})

    listed = preset_client.get("/api/caption-presets").json()
    defaults = [item for item in listed["presets"] if item["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == second["id"]


def test_import_valid_json(preset_client, temp_backend_dirs):
    payload = {
        "schema_version": CAPTION_PRESET_SCHEMA_VERSION,
        "preset": {
            "name": "Imported Look",
            "style": _custom_style(animation_type="fade").model_dump(mode="json"),
        },
    }
    response = preset_client.post("/api/caption-presets/import", json=payload)
    assert response.status_code == 200
    imported = response.json()["imported"]
    assert len(imported) == 1
    assert imported[0]["name"] == "Imported Look"


def test_reject_invalid_schema_version(preset_client, temp_backend_dirs):
    payload = {
        "schema_version": 99,
        "preset": {
            "name": "Bad Version",
            "style": _custom_style().model_dump(mode="json"),
        },
    }
    response = preset_client.post("/api/caption-presets/import", json=payload)
    assert response.status_code == 422


def test_reject_malformed_color(preset_client, temp_backend_dirs):
    response = preset_client.post(
        "/api/caption-presets",
        json={
            "name": "Bad Color",
            "style": _custom_style(text_color="red").model_dump(mode="json"),
        },
    )
    assert response.status_code == 422


def test_export_format(preset_client, temp_backend_dirs):
    response = preset_client.get("/api/caption-presets/minimal-clean/export")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == CAPTION_PRESET_SCHEMA_VERSION
    assert body["preset"]["name"] == "Minimal Clean"
    assert "font_family" in body["preset"]["style"]


def test_persistence_across_reload(temp_backend_dirs):
    create_caption_preset(
        CreateCaptionPresetRequest(name="Persisted", style=_custom_style(font_size=31))
    )
    store_path = get_caption_presets_store_path()
    assert store_path.exists()

    reloaded = list_caption_presets()
    custom = [item for item in reloaded.presets if item.name == "Persisted"]
    assert len(custom) == 1
    assert custom[0].style.font_size == 31


def test_existing_project_caption_style_unchanged_when_default_changes(
    sample_project,
    temp_backend_dirs,
    preset_client,
):
    from tests.test_caption_render import _export_and_caption

    exported = _export_and_caption(sample_project)
    before = preset_client.get(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions"
    )
    assert before.status_code == 200
    original_style = before.json()["style"]

    custom = preset_client.post(
        "/api/caption-presets",
        json={
            "name": "New Default",
            "style": _custom_style(
                text_color="#010203",
                words_per_group="1",
                animation_type="bounce",
            ).model_dump(mode="json"),
        },
    ).json()
    preset_client.patch(
        f"/api/caption-presets/{custom['id']}",
        json={"is_default": True},
    )

    after = preset_client.get(
        f"/api/projects/{sample_project['project_id']}/clips/{exported.clip_id}/captions"
    )
    assert after.json()["style"] == original_style


def test_newly_generated_captions_use_default_preset(
    sample_project,
    temp_backend_dirs,
    preset_client,
):
    from tests.test_clip_captions import _set_video_metadata, _write_transcript, _sample_transcript
    from tests.test_caption_render import _fake_ffmpeg_run_factory
    from unittest.mock import patch
    from app.services.clip_export import export_project_clip

    custom = preset_client.post(
        "/api/caption-presets",
        json={
            "name": "Generation Default",
            "style": _custom_style(
                text_color="#112233",
                words_per_group="2",
            ).model_dump(mode="json"),
        },
    ).json()
    preset_client.patch(
        f"/api/caption-presets/{custom['id']}",
        json={"is_default": True},
    )

    _set_video_metadata(sample_project)
    _write_transcript(sample_project["project_id"], _sample_transcript(sample_project["project_id"]))
    with (
        patch("app.services.clip_export._run_command", side_effect=_fake_ffmpeg_run_factory()),
        patch("app.services.video_processing._run_command", side_effect=_fake_ffmpeg_run_factory()),
    ):
        exported = export_project_clip(
            sample_project["project_id"],
            start_time=1.0,
            end_time=5.0,
        )

    with patch(
        "app.services.video_processing._run_command",
        side_effect=_fake_ffmpeg_run_factory(),
    ):
        generated = generate_clip_captions(sample_project["project_id"], exported.clip_id)

    assert generated.style.text_color == "#112233"
    assert generated.style.words_per_group == CaptionWordsPerGroup.TWO
