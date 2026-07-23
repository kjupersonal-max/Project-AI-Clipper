from __future__ import annotations

import json

import pytest

from app.models.project import ProcessingStatus, TranscriptDocument, TranscriptSegment
from app.services.clip_selection import select_project_clips
from app.services.project_store import load_project, save_project
from app.services.timeline_analysis import analyze_project_timeline


def _write_transcript(sample_project, temp_backend_dirs, segments: list[TranscriptSegment]) -> None:
    project_id = sample_project["project_id"]
    transcript_dir = temp_backend_dirs["transcripts_dir"] / project_id
    transcript_dir.mkdir(parents=True, exist_ok=True)
    document = TranscriptDocument(
        project_id=project_id,
        language="en",
        duration=max((segment.end for segment in segments), default=0.0),
        segment_count=len(segments),
        word_count=0,
        segments=segments,
    )
    (transcript_dir / "transcript.json").write_text(
        json.dumps(document.model_dump(mode="json"), indent=2),
        encoding="utf-8",
    )
    project = load_project(project_id)
    project.transcription_status = ProcessingStatus.COMPLETED
    project.transcript_path = f"{project_id}/transcript.json"
    save_project(project)


@pytest.fixture()
def long_clip_segments() -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    cursor = 0.0
    texts = [
        "Wait, that was insane!",
        "lol that was actually funny",
        "Because this tip helps you learn the mechanic",
        "No way, that clutch was crazy!",
        "Holy wow, that reveal changed everything!",
        "Wait, watch out for the setup before the payoff.",
        "That joke lands because the timing is perfect.",
        "This tip alone saves hours of grinding.",
        "No way, that actually worked!",
        "Let's go, that is the complete story!",
    ]
    for index, text in enumerate(texts):
        start = cursor
        end = start + 8.0
        segments.append(TranscriptSegment(id=index, start=start, end=end, text=text, words=[]))
        cursor = end + 0.5
    return segments


def test_candidates_meet_fifteen_second_minimum(
    sample_project,
    temp_backend_dirs,
    long_clip_segments,
):
    _write_transcript(sample_project, temp_backend_dirs, long_clip_segments)
    analyze_project_timeline(sample_project["project_id"])
    project = load_project(sample_project["project_id"])
    project.analysis_status = ProcessingStatus.COMPLETED
    save_project(project)

    document = select_project_clips(sample_project["project_id"], min_score=0.0)
    assert document.candidate_count >= 1
    for candidate in document.candidates:
        assert candidate.duration >= 15.0
        assert candidate.duration_class in {"short", "medium", "long"}


def test_short_hook_expands_to_minimum_duration(
    sample_project,
    temp_backend_dirs,
):
    segments = [
        TranscriptSegment(id=0, start=0.0, end=3.0, text="Wait, that was insane!", words=[]),
        TranscriptSegment(id=1, start=3.0, end=8.0, text="Because this tip helps you learn fast", words=[]),
        TranscriptSegment(id=2, start=8.0, end=14.0, text="No way, that clutch was crazy!", words=[]),
        TranscriptSegment(id=3, start=14.0, end=22.0, text="That payoff makes the whole setup worth it.", words=[]),
        TranscriptSegment(id=4, start=22.0, end=30.0, text="Exactly, and that is the complete answer.", words=[]),
    ]
    _write_transcript(sample_project, temp_backend_dirs, segments)
    analyze_project_timeline(sample_project["project_id"])
    project = load_project(sample_project["project_id"])
    project.analysis_status = ProcessingStatus.COMPLETED
    save_project(project)

    document = select_project_clips(sample_project["project_id"], min_score=0.0)
    assert document.candidate_count >= 1
    assert all(candidate.duration >= 15.0 for candidate in document.candidates)
