from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from app.core.config import settings
from app.models.project import SegmentAnalysis, TranscriptSegment
from app.services.analysis.base import AnalysisProvider, AnalysisProviderError
from app.services.analysis.response_validation import validate_llm_segment_results

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You analyze transcript segments from long-form videos to identify moments that work as short-form clips (15-60 seconds).

Score each requested TARGET segment on a 0-10 scale:
- excitement_score: energy, hype, surprise, intensity
- humor_score: jokes, wit, comedic timing
- suspense_score: tension, anticipation, stakes
- educational_score: clear teaching, insight, or explanation
- standalone_score: how well the moment makes sense without prior video context
- context_dependency_score: how much prior context is required (10 = needs lots of context)

Also assign:
- emotion: one concise label (e.g. excited, humorous, tense, informative, surprised, frustrated, neutral)
- clip_candidate: true only when the segment belongs in a short-form clip
- reason: one concise sentence explaining the scores and clip decision

Clip selection principles:
- Reward strong opening hooks, clear context, emotional or informational payoff, self-contained moments, and natural endings.
- Penalize fragments, filler, references that require missing context, weak endings, and repetitive speech.
- Do NOT reward isolated excitement alone. A loud reaction without setup or payoff is not a good clip.
- Prefer coherent mini-stories over isolated reactions.

Return strict JSON only with this shape:
{"segments":[{"segment_id":0,"emotion":"...","excitement_score":0.0,"humor_score":0.0,"suspense_score":0.0,"educational_score":0.0,"standalone_score":0.0,"context_dependency_score":0.0,"clip_candidate":false,"reason":"..."}]}

Analyze ONLY the TARGET segments listed in the user message. Use CONTEXT segments for judgment only."""

TRANSIENT_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class OpenAIAnalysisProvider(AnalysisProvider):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str | None = None,
        timeout_seconds: int | None = None,
        max_transcript_chars: int | None = None,
        context_segment_count: int | None = None,
        max_retries: int | None = None,
        http_client: httpx.Client | None = None,
    ):
        self._model_name = model_name
        self._api_key = api_key
        self._base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self._timeout_seconds = timeout_seconds or settings.analysis_timeout_seconds
        self._max_transcript_chars = max_transcript_chars or settings.analysis_max_transcript_chars
        self._context_segment_count = context_segment_count or settings.analysis_context_segments
        self._max_retries = max_retries if max_retries is not None else settings.analysis_max_retries
        self._http_client = http_client
        self._all_segments: list[TranscriptSegment] = []
        self._segment_index: dict[int, int] = {}

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str | None:
        return self._model_name

    def bind_transcript(self, segments: list[TranscriptSegment]) -> None:
        self._all_segments = list(segments)
        self._segment_index = {segment.id: index for index, segment in enumerate(segments)}

    def analyze_batch(self, segments: list[TranscriptSegment]) -> list[SegmentAnalysis]:
        if not segments:
            return []

        user_prompt = self._build_user_prompt(segments)
        response_payload = self._call_chat_completions(user_prompt)
        raw_segments = self._extract_segments_payload(response_payload)
        return validate_llm_segment_results(
            target_segments=segments,
            payload_segments=raw_segments,
        )

    def _build_user_prompt(self, target_segments: list[TranscriptSegment]) -> str:
        context_segments = self._collect_context_segments(target_segments)
        context_lines = [
            self._format_segment_line(segment, role="CONTEXT")
            for segment in context_segments
        ]
        target_lines = [
            self._format_segment_line(segment, role="TARGET")
            for segment in target_segments
        ]

        prompt_parts = [
            "Analyze the TARGET transcript segments for short-form clip potential.",
            "Use CONTEXT segments only for neighboring context; do not return results for them.",
            "",
            "CONTEXT:",
        ]
        prompt_parts.extend(context_lines or ["(none)"])
        prompt_parts.extend(["", "TARGET:"])
        prompt_parts.extend(target_lines)
        prompt_parts.extend(
            [
                "",
                f"Return JSON for exactly these segment_ids: "
                f"{[segment.id for segment in target_segments]}.",
            ]
        )

        prompt = "\n".join(prompt_parts)
        if len(prompt) > self._max_transcript_chars:
            trimmed_target_lines = target_lines
            while len(prompt) > self._max_transcript_chars and len(trimmed_target_lines) > 1:
                trimmed_target_lines = trimmed_target_lines[:-1]
                prompt_parts = [
                    "Analyze the TARGET transcript segments for short-form clip potential.",
                    "Use CONTEXT segments only for neighboring context; do not return results for them.",
                    "",
                    "CONTEXT:",
                    *(context_lines or ["(none)"]),
                    "",
                    "TARGET:",
                    *trimmed_target_lines,
                    "",
                    f"Return JSON for exactly these segment_ids: "
                    f"{[segment.id for segment in target_segments[: len(trimmed_target_lines)]]}.",
                ]
                prompt = "\n".join(prompt_parts)

            if len(prompt) > self._max_transcript_chars:
                raise AnalysisProviderError(
                    "Transcript batch exceeds configured analysis character limit."
                )

            if len(trimmed_target_lines) < len(target_segments):
                raise AnalysisProviderError(
                    "Transcript batch exceeds configured analysis character limit."
                )

        return prompt

    def _collect_context_segments(self, target_segments: list[TranscriptSegment]) -> list[TranscriptSegment]:
        if not self._all_segments or self._context_segment_count <= 0:
            return []

        target_ids = {segment.id for segment in target_segments}
        context: list[TranscriptSegment] = []
        seen: set[int] = set()

        for segment in target_segments:
            index = self._segment_index.get(segment.id)
            if index is None:
                continue
            start = max(0, index - self._context_segment_count)
            end = min(len(self._all_segments), index + self._context_segment_count + 1)
            for neighbor in self._all_segments[start:end]:
                if neighbor.id in target_ids or neighbor.id in seen:
                    continue
                seen.add(neighbor.id)
                context.append(neighbor)

        context.sort(key=lambda item: item.start)
        return context

    @staticmethod
    def _format_segment_line(segment: TranscriptSegment, *, role: str) -> str:
        return (
            f"- [{role}] segment_id={segment.id} "
            f"({segment.start:.2f}s-{segment.end:.2f}s): {segment.text.strip()}"
        )

    def _call_chat_completions(self, user_prompt: str) -> dict[str, Any]:
        request_body = {
            "model": self._model_name,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        attempt = 0
        last_error: Exception | None = None

        while attempt <= self._max_retries:
            try:
                payload = self._post_json(
                    f"{self._base_url}/chat/completions",
                    headers=headers,
                    body=request_body,
                )
                self._log_usage(payload)
                return payload
            except AnalysisProviderError as exc:
                last_error = exc
                if not exc.message.startswith("Transient provider failure"):
                    raise
            except httpx.TimeoutException as exc:
                last_error = exc
                logger.warning(
                    "OpenAI analysis request timed out (attempt %s/%s, model=%s)",
                    attempt + 1,
                    self._max_retries + 1,
                    self._model_name,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                logger.warning(
                    "OpenAI analysis HTTP error (attempt %s/%s, model=%s): %s",
                    attempt + 1,
                    self._max_retries + 1,
                    self._model_name,
                    exc,
                )

            attempt += 1
            if attempt <= self._max_retries:
                time.sleep(min(0.5 * attempt, 2.0))

        message = "Analysis provider request failed after retries."
        if isinstance(last_error, AnalysisProviderError):
            message = last_error.message
        raise AnalysisProviderError(message) from last_error

    def _post_json(self, url: str, *, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = httpx.Client(timeout=self._timeout_seconds)

        try:
            response = client.post(url, headers=headers, json=body)
        finally:
            if owns_client and client is not None:
                client.close()

        if response.status_code in TRANSIENT_STATUS_CODES:
            raise AnalysisProviderError(
                f"Transient provider failure (HTTP {response.status_code})."
            )

        if response.status_code >= 400:
            detail = self._safe_error_detail(response)
            raise AnalysisProviderError(
                f"Analysis provider request failed (HTTP {response.status_code}): {detail}"
            )

        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise AnalysisProviderError("Analysis provider returned malformed JSON.") from exc

    @staticmethod
    def _safe_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except json.JSONDecodeError:
            text = response.text.strip()
            return text[:180] if text else "Unknown provider error."

        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()[:180]
            message = payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:180]
        return "Unknown provider error."

    @staticmethod
    def _extract_segments_payload(response_payload: dict[str, Any]) -> list[dict]:
        try:
            content = response_payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisProviderError(
                "Analysis provider returned an unexpected response shape."
            ) from exc

        if not isinstance(content, str) or not content.strip():
            raise AnalysisProviderError("Analysis provider returned empty content.")

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise AnalysisProviderError("Analysis provider returned malformed JSON content.") from exc

        if not isinstance(parsed, dict):
            raise AnalysisProviderError("Analysis provider JSON root must be an object.")

        segments = parsed.get("segments")
        if not isinstance(segments, list):
            raise AnalysisProviderError("Analysis provider JSON must include a segments array.")

        return segments

    @staticmethod
    def _log_usage(response_payload: dict[str, Any]) -> None:
        usage = response_payload.get("usage")
        if not isinstance(usage, dict):
            return
        logger.info(
            "OpenAI analysis usage prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            usage.get("prompt_tokens"),
            usage.get("completion_tokens"),
            usage.get("total_tokens"),
        )
