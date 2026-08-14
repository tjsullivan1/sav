"""Runtime configuration for the blog-to-podcast app.

Settings are resolved from environment variables and may be overridden at
runtime by values entered in the Streamlit sidebar.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
MAX_SUMMARY_CHARS = 2000


class Settings(BaseModel):
    """Credentials and model settings needed to generate a podcast."""

    azure_openai_base_url: str = Field(
        default="",
        description="Azure OpenAI v1 base URL, e.g. https://<resource>.openai.azure.com/openai/v1/",
    )
    azure_openai_deployment: str = Field(
        default="", description="Azure OpenAI chat model deployment name."
    )
    azure_openai_api_key: str = Field(default="", description="Azure OpenAI API key.")
    elevenlabs_api_key: str = Field(default="", description="ElevenLabs API key.")
    firecrawl_api_key: str = Field(default="", description="Firecrawl API key.")
    voice_id: str = Field(default=DEFAULT_VOICE_ID, description="ElevenLabs voice identifier.")
    tts_model_id: str = Field(default=DEFAULT_TTS_MODEL, description="ElevenLabs TTS model id.")

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables, falling back to empty strings."""
        return cls(
            azure_openai_base_url=os.getenv("AZURE_OPENAI_BASE_URL", ""),
            azure_openai_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", ""),
            azure_openai_api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            firecrawl_api_key=os.getenv("FIRECRAWL_API_KEY", ""),
            voice_id=os.getenv("ELEVENLABS_VOICE_ID", DEFAULT_VOICE_ID),
            tts_model_id=os.getenv("ELEVENLABS_MODEL_ID", DEFAULT_TTS_MODEL),
        )

    def missing_fields(self) -> list[str]:
        """Return the human-readable names of required settings that are still empty."""
        required = {
            "Azure OpenAI v1 Base URL": self.azure_openai_base_url,
            "Azure OpenAI Deployment Name": self.azure_openai_deployment,
            "Azure OpenAI API Key": self.azure_openai_api_key,
            "ElevenLabs API Key": self.elevenlabs_api_key,
            "Firecrawl API Key": self.firecrawl_api_key,
        }
        return [name for name, value in required.items() if not value.strip()]

    @property
    def is_complete(self) -> bool:
        """Whether every required credential has been supplied."""
        return not self.missing_fields()
