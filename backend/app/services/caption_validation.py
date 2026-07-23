from __future__ import annotations

from app.models.project import CaptionSegment, CaptionWord


class ClipCaptionsValidationError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def round_caption_time(value: float) -> float:
    return round(value, 3)


def validate_caption_segments(segments: list[CaptionSegment], clip_duration: float) -> None:
    for segment in segments:
        if segment.start < 0:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} start time must be non-negative."
            )
        if segment.end <= segment.start:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} end time must be after start time."
            )
        if segment.end > clip_duration + 0.001:
            raise ClipCaptionsValidationError(
                f"Caption {segment.id} end time exceeds clip duration ({clip_duration:.3f}s)."
            )
        for word in segment.words:
            if word.start < 0:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word start time must be non-negative."
                )
            if word.end <= word.start:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word end time must be after start time."
                )
            if word.end > clip_duration + 0.001:
                raise ClipCaptionsValidationError(
                    f"Caption {segment.id} word end time exceeds clip duration."
                )
