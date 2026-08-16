import os

import pytest

from blog_to_podcast.config import DEFAULT_TTS_MODEL, DEFAULT_VOICE_ID, Settings

REQUIRED = {
    "azure_openai_base_url": "https://example.openai.azure.com/openai/v1/",
    "azure_openai_deployment": "gpt-4o",
    "azure_openai_api_key": "aoai-key",
    "elevenlabs_api_key": "el-key",
    "firecrawl_api_key": "fc-key",
}

ENV_VARS = [
    "AZURE_OPENAI_BASE_URL",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_OPENAI_API_KEY",
    "ELEVENLABS_API_KEY",
    "FIRECRAWL_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ELEVENLABS_MODEL_ID",
]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_empty_and_incomplete() -> None:
    settings = Settings()
    assert not settings.is_complete
    assert len(settings.missing_fields()) == len(REQUIRED)
    assert settings.voice_id == DEFAULT_VOICE_ID
    assert settings.tts_model_id == DEFAULT_TTS_MODEL


def test_complete_settings_have_no_missing_fields() -> None:
    settings = Settings(**REQUIRED)
    assert settings.is_complete
    assert settings.missing_fields() == []


def test_whitespace_only_values_count_as_missing() -> None:
    settings = Settings(**{**REQUIRED, "azure_openai_api_key": "   "})
    assert settings.missing_fields() == ["Azure OpenAI API Key"]


def test_from_env_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", REQUIRED["azure_openai_base_url"])
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", REQUIRED["azure_openai_deployment"])
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", REQUIRED["azure_openai_api_key"])
    monkeypatch.setenv("ELEVENLABS_API_KEY", REQUIRED["elevenlabs_api_key"])
    monkeypatch.setenv("FIRECRAWL_API_KEY", REQUIRED["firecrawl_api_key"])
    monkeypatch.setenv("ELEVENLABS_VOICE_ID", "custom-voice")

    settings = Settings.from_env()

    assert settings.is_complete
    assert settings.voice_id == "custom-voice"
    assert settings.tts_model_id == DEFAULT_TTS_MODEL
    assert os.getenv("ELEVENLABS_MODEL_ID") is None
