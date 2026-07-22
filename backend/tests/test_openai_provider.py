from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from app.core.config import settings
from app.models.project import TranscriptSegment
from app.services.analysis.base import AnalysisProviderError
from app.services.analysis.openai_provider import OpenAIAnalysisProvider
from app.services.analysis.registry import describe_analysis_provider, resolve_analysis_provider
from app.services.analysis.response_validation import validate_llm_segment_results


def _segment(segment_id: int, text: str) -> TranscriptSegment:
    return TranscriptSegment(
        id=segment_id,
        start=float(segment_id),
        end=float(segment_id + 1),
        text=text,
        words=[],
    )


def _valid_payload(segment_id: int) -> dict:
    return {
        "segment_id": segment_id,
        "emotion": "excited",
        "excitement_score": 7.5,
        "humor_score": 2.0,
        "suspense_score": 3.0,
        "educational_score": 4.0,
        "standalone_score": 8.0,
        "context_dependency_score": 2.0,
        "clip_candidate": True,
        "reason": "Strong standalone hook with clear payoff.",
    }


def _mock_openai_response(segments: list[dict]) -> dict:
    return {
        "choices": [
            {
                "message": {
                    "content": json.dumps({"segments": segments}),
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 80,
            "total_tokens": 200,
        },
    }


class MockTransport(httpx.BaseTransport):
    def __init__(self, handler):
        self.handler = handler

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.handler(request)


def _build_provider(*, handler, **kwargs) -> OpenAIAnalysisProvider:
    transport = MockTransport(handler)
    client = httpx.Client(transport=transport)
    provider = OpenAIAnalysisProvider(
        model_name="gpt-4o-mini",
        api_key="test-key",
        http_client=client,
        **kwargs,
    )
    provider.bind_transcript(
        [
            _segment(0, "Wait, that was insane!"),
            _segment(1, "lol that was actually funny"),
            _segment(2, "Because this tip helps you learn the mechanic"),
        ]
    )
    return provider


def test_openai_provider_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content.decode("utf-8"))
        assert body["model"] == "gpt-4o-mini"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(
            200,
            json=_mock_openai_response([_valid_payload(0), _valid_payload(1)]),
        )

    provider = _build_provider(handler=handler)
    results = provider.analyze_batch(
        [_segment(0, "Wait, that was insane!"), _segment(1, "lol that was actually funny")]
    )

    assert len(results) == 2
    assert results[0].segment_id == 0
    assert results[0].text == "Wait, that was insane!"
    assert results[0].clip_candidate is True


def test_openai_provider_malformed_json():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "{not valid"}}],
            },
        )

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError, match="malformed JSON"):
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])


def test_openai_provider_missing_segment_ids():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_mock_openai_response([_valid_payload(0)]),
        )

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError, match="omitted results"):
        provider.analyze_batch(
            [_segment(0, "Wait, that was insane!"), _segment(1, "lol that was actually funny")]
        )


def test_openai_provider_duplicate_segment_ids():
    payload = _valid_payload(0)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_mock_openai_response([payload, payload]),
        )

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError, match="duplicate"):
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])


def test_openai_provider_unknown_segment_ids():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_mock_openai_response([_valid_payload(99)]),
        )

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError, match="unknown segment_id"):
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])


def test_openai_provider_invalid_score_ranges():
    payload = _valid_payload(0)
    payload["excitement_score"] = 11.0

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_mock_openai_response([payload]),
        )

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError, match="invalid scores"):
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])


def test_validate_llm_segment_results_empty_payload():
    with pytest.raises(AnalysisProviderError, match="no segment results"):
        validate_llm_segment_results(
            target_segments=[_segment(0, "hello")],
            payload_segments=[],
        )


def test_openai_provider_transient_retry_then_success():
    calls = {"count": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": {"message": "Service unavailable"}})
        return httpx.Response(200, json=_mock_openai_response([_valid_payload(0)]))

    provider = _build_provider(handler=handler, max_retries=2)
    results = provider.analyze_batch([_segment(0, "Wait, that was insane!")])

    assert calls["count"] == 2
    assert len(results) == 1


def test_openai_provider_timeout_retries_exhausted():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=MagicMock())

    provider = _build_provider(handler=handler, max_retries=1)
    with pytest.raises(AnalysisProviderError, match="failed after retries"):
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])


def test_openai_provider_does_not_leak_api_key_in_errors():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "Invalid API key"}})

    provider = _build_provider(handler=handler)
    with pytest.raises(AnalysisProviderError) as exc_info:
        provider.analyze_batch([_segment(0, "Wait, that was insane!")])

    assert "test-key" not in exc_info.value.message


def test_auto_provider_selection_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "auto")
    monkeypatch.setattr(settings, "analysis_api_key", "")

    provider = resolve_analysis_provider()
    assert provider.provider_name == "heuristic"


def test_auto_provider_selection_with_api_key(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "auto")
    monkeypatch.setattr(settings, "analysis_api_key", "sk-test")
    monkeypatch.setattr(settings, "analysis_external_provider", "openai")

    provider = resolve_analysis_provider()
    assert provider.provider_name == "openai"
    assert provider.model_name == settings.analysis_model


def test_describe_analysis_provider_openai_configured(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "openai")
    monkeypatch.setattr(settings, "analysis_api_key", "sk-test")

    description = describe_analysis_provider()
    assert description["provider_name"] == "openai"
    assert description["available"] is True
    assert description["is_heuristic_fallback"] is False
