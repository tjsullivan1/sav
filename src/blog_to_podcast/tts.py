"""Text-to-speech generation using the ElevenLabs API."""

from __future__ import annotations

import logging
from collections.abc import Iterable

from elevenlabs import ElevenLabs

from blog_to_podcast.config import Settings

logger = logging.getLogger(__name__)


class AudioGenerationError(RuntimeError):
    """Raised when text-to-speech produces no audio."""


def _collect(chunks: Iterable[bytes] | bytes) -> bytes:
    """Join a stream of audio chunks into a single bytes payload."""
    if isinstance(chunks, bytes | bytearray):
        return bytes(chunks)
    return b"".join(chunk for chunk in chunks if chunk)


def text_to_speech(text: str, settings: Settings, client: ElevenLabs | None = None) -> bytes:
    """Convert summary text into MP3 audio bytes.

    Args:
        text: The narration script to synthesize.
        settings: Resolved credentials and voice configuration.
        client: Optional pre-built ElevenLabs client, primarily for testing.

    Returns:
        The MP3 audio payload.

    Raises:
        AudioGenerationError: If the API returns no audio data.

    """
    client = client or ElevenLabs(api_key=settings.elevenlabs_api_key)
    logger.info("generating audio", extra={"chars": len(text), "voice_id": settings.voice_id})

    audio = client.text_to_speech.convert(
        text=text,
        voice_id=settings.voice_id,
        model_id=settings.tts_model_id,
    )
    audio_bytes = _collect(audio)

    if not audio_bytes:
        raise AudioGenerationError("Text-to-speech returned no audio data.")
    return audio_bytes
