"""Runtime configuration for the local blog-to-podcast app."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_TTS_MODEL = "eleven_multilingual_v2"
MAX_SUMMARY_CHARS = 2000
DEFAULT_TTS_CHARACTER_CAP = 5000
DEFAULT_NARRATION_CONFIRMATION_THRESHOLD = 10000
DEFAULT_NARRATION_CHARACTERS_PER_MINUTE = 900


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
    storage_account_name: str = Field(
        default="",
        description="Azure Storage account name.",
        validation_alias="AZURE_STORAGE_ACCOUNT_NAME",
    )
    entra_tenant_id: str = Field(
        default="", description="Microsoft Entra tenant ID.", validation_alias="ENTRA_TENANT_ID"
    )
    api_application_id_uri: str = Field(
        default="",
        description="Microsoft Entra API application ID URI suffix.",
        validation_alias="API_APPLICATION_ID_URI",
    )
    approved_user_subjects_csv: str = Field(
        default="",
        description="Comma-separated Entra object IDs authorized for the Episode API.",
        validation_alias="APPROVED_USER_SUBJECTS",
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
    tts_character_cap: int = Field(
        default=DEFAULT_TTS_CHARACTER_CAP,
        ge=1,
        description="Maximum characters accepted by the active text-to-speech model.",
        validation_alias="ELEVENLABS_TTS_CHARACTER_CAP",
    )
    narration_confirmation_threshold: int = Field(
        default=DEFAULT_NARRATION_CONFIRMATION_THRESHOLD,
        ge=0,
        description="Narration character count that requires confirmation before synthesis.",
        validation_alias="NARRATION_CONFIRMATION_THRESHOLD",
    )
    narration_characters_per_minute: int = Field(
        default=DEFAULT_NARRATION_CHARACTERS_PER_MINUTE,
        ge=1,
        description="Estimated spoken characters per minute for Narration preflight.",
        validation_alias="NARRATION_CHARACTERS_PER_MINUTE",
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

    @property
    def approved_user_subjects(self) -> set[str]:
        """Return authorized Entra object IDs from the deployment configuration."""
        return {
            subject.strip()
            for subject in self.approved_user_subjects_csv.split(",")
            if subject.strip()
        }
