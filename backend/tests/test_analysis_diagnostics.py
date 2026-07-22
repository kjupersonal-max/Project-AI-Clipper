from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def test_analysis_provider_diagnostics_heuristic(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "auto")
    monkeypatch.setattr(settings, "analysis_api_key", "")

    client = TestClient(app)
    response = client.get("/api/projects/analysis/provider-diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_provider"] == "heuristic"
    assert body["is_heuristic_fallback"] is True
    assert body["available"] is True


def test_analysis_provider_diagnostics_openai_configured(monkeypatch):
    monkeypatch.setattr(settings, "analysis_provider", "openai")
    monkeypatch.setattr(settings, "analysis_api_key", "sk-test")

    client = TestClient(app)
    response = client.get("/api/projects/analysis/provider-diagnostics?dry_run=true")
    assert response.status_code == 200
    body = response.json()
    assert body["resolved_provider"] == "openai"
    assert body["is_heuristic_fallback"] is False
    assert body["dry_run"] == "configuration_valid"
