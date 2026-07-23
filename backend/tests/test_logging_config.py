from __future__ import annotations

import logging

from app.core.logging_config import configure_logging
from app.services.pipeline_timing import log_stage_event, log_timing_summary


def test_configure_logging_enables_app_service_info_logs(caplog) -> None:
    caplog.set_level(logging.INFO)
    configure_logging("INFO")

    service_logger = logging.getLogger("app.services.transcription_pipeline")
    service_logger.info("transcription pipeline visibility probe")

    assert any(
        "transcription pipeline visibility probe" in record.message
        for record in caplog.records
    )


def test_pipeline_timing_helpers_emit_info_logs(caplog) -> None:
    caplog.set_level(logging.INFO)
    configure_logging("INFO")

    log_stage_event(
        "primary_transcription",
        "end",
        project_id="test-project",
        elapsed_seconds=12.345,
        word_count=42,
    )
    log_timing_summary(
        project_id="test-project",
        pipeline="transcription",
        total_seconds=600.0,
        primary_transcription="480.000s",
        secondary_transcription="0.000s",
        recovery="60.000s",
        skipped="secondary_no_vad,recovery",
    )

    messages = [record.message for record in caplog.records]
    assert any("stage=primary_transcription event=end" in message for message in messages)
    assert any("primary_transcription=480.000s" in message for message in messages)
    assert any("skipped=secondary_no_vad,recovery" in message for message in messages)
    assert any("total=600.000s" in message for message in messages)
