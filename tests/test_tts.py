from collections.abc import Iterator

import pytest

from blog_to_podcast.config import Settings
from blog_to_podcast.tts import AudioGenerationError, text_to_speech


class FakeTextToSpeech:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[dict[str, str]] = []

    def convert(self, *, text: str, voice_id: str, model_id: str) -> object:
        self.calls.append({"text": text, "voice_id": voice_id, "model_id": model_id})
        return self.payload


class FakeClient:
    def __init__(self, payload: object) -> None:
        self.text_to_speech = FakeTextToSpeech(payload)


@pytest.fixture
def settings() -> Settings:
    return Settings(elevenlabs_api_key="el-key")


def _chunks() -> Iterator[bytes]:
    yield b"abc"
    yield b""
    yield b"def"


def test_text_to_speech_joins_streamed_chunks(settings: Settings) -> None:
    client = FakeClient(_chunks())

    audio = text_to_speech("hello", settings, client=client)

    assert audio == b"abcdef"
    assert client.text_to_speech.calls[0]["voice_id"] == settings.voice_id
    assert client.text_to_speech.calls[0]["model_id"] == settings.tts_model_id


def test_text_to_speech_accepts_raw_bytes(settings: Settings) -> None:
    audio = text_to_speech("hello", settings, client=FakeClient(b"raw"))
    assert audio == b"raw"


def test_text_to_speech_raises_when_no_audio(settings: Settings) -> None:
    with pytest.raises(AudioGenerationError):
        text_to_speech("hello", settings, client=FakeClient(iter([])))
