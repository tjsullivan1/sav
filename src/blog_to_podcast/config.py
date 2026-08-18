"""Runtime configuration for the local blog-to-podcast app."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
MAX_SUMMARY_CHARS = 2000


class Settings(BaseSettings):
    """Credentials and model settings needed to generate a podcast."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    azure_openai_base_url: str = Field(
        default="",
        description="Azure OpenAI v1 base URL, e.g. https://<resource>.openai.azure.com/openai/v1/",
        validation_alias="AZURE_OPENAI_BASE_URL",
    )
    azure_openai_deployment: str = Field(
        default="",
        description="Azure OpenAI chat model deployment name.",
        validation_alias="AZURE_OPENAI_DEPLOYMENT",
    )
    azure_openai_api_key: str = Field(
        default="", description="Azure OpenAI API key.", validation_alias="AZURE_OPENAI_API_KEY"
    )
    elevenlabs_api_key: str = Field(
        default="", description="ElevenLabs API key.", validation_alias="ELEVENLABS_API_KEY"
    )
    firecrawl_api_key: str = Field(
        default="", description="Firecrawl API key.", validation_alias="FIRECRAWL_API_KEY"
    )
    voice_id: str = Field(
        default=DEFAULT_VOICE_ID,
        description="ElevenLabs voice identifier.",
        validation_alias="ELEVENLABS_VOICE_ID",
    )
    tts_model_id: str = Field(
        default=DEFAULT_TTS_MODEL,
        description="ElevenLabs TTS model id.",
        validation_alias="ELEVENLABS_MODEL_ID",
    )

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings from environment variables and an optional local ``.env`` file."""
        return cls()

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

    def startup_feedback(self) -> str:
        """Return actionable feedback when required configuration is incomplete."""
        missing_variables = {
            "AZURE_OPENAI_BASE_URL": self.azure_openai_base_url,
            "AZURE_OPENAI_DEPLOYMENT": self.azure_openai_deployment,
            "AZURE_OPENAI_API_KEY": self.azure_openai_api_key,
            "ELEVENLABS_API_KEY": self.elevenlabs_api_key,
            "FIRECRAWL_API_KEY": self.firecrawl_api_key,
        }
        missing = [name for name, value in missing_variables.items() if not value.strip()]
        if not missing:
            return ""
        return f"Set the following required environment variables: {', '.join(missing)}."

    @property
    def is_complete(self) -> bool:
        """Whether every required credential has been supplied."""
        return not self.missing_fields()
