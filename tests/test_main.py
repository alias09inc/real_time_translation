"""Tests for the project entrypoints and configuration."""

import pytest

from real_time_translation.config import Config


def test_config_from_env_without_zoom(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    monkeypatch.delenv("ZOOM_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOOM_CLIENT_SECRET", raising=False)

    config = Config.from_env(env_file=env_file, require_zoom=False)
    assert config.deepgram_api_key == "test-deepgram"
    assert config.llm_provider == "openai"


def test_config_from_env_requires_zoom(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    monkeypatch.setenv("DEEPGRAM_API_KEY", "test-deepgram")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")

    monkeypatch.delenv("ZOOM_CLIENT_ID", raising=False)
    monkeypatch.delenv("ZOOM_CLIENT_SECRET", raising=False)

    with pytest.raises(ValueError, match="ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET"):
        Config.from_env(env_file=env_file, require_zoom=True)
