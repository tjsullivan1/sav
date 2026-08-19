"""Cloud runtime composition for the authenticated API and private queue worker."""

from __future__ import annotations

from datetime import UTC, datetime

import jwt
from agno.agent import Agent
from agno.models.openai import OpenAIChat

from blog_to_podcast.api import create_app
from blog_to_podcast.cloud import (
    AzureBlobStorage,
    AzureGenerationJobRepository,
    AzureGenerationQueue,
    AzureQueueWorker,
    AzureTableStorage,
    CloudCompletedEpisodeStore,
    CloudEpisodeStore,
    CloudGenerationProvider,
)
from blog_to_podcast.config import Settings
from blog_to_podcast.episodes import (
    ElevenLabsAudioSynthesizer,
    Episode,
    EpisodeRequest,
    FfmpegAudioDurationProbe,
    FfmpegAudioStitcher,
    FirecrawlArticleRetriever,
    NarrationEstimate,
    NarrationScriptStrategy,
    ScriptStrategy,
    SummaryScriptStrategy,
)
from blog_to_podcast.identity import EntraIdentityResolver
from blog_to_podcast.jobs import GenerationJobService, GenerationProvider, GenerationProviderError


class SystemClock:
    """Clock backed by the current UTC time."""

    def now(self) -> datetime:
        """Return the current UTC time."""
        return datetime.now(UTC)


class ApiGenerationProvider:
    """Prevents the public API process from loading worker-only provider credentials."""

    def retrieve(self, request: EpisodeRequest) -> EpisodeRequest:
        """Reject a worker operation attempted in the API process."""
        raise GenerationProviderError("Generation Jobs must run in the private worker.")

    def find_existing(self, request: EpisodeRequest) -> Episode | None:
        """Return no Episode because the API does not process jobs."""
        return None

    def confirmation_estimate(self, request: EpisodeRequest) -> NarrationEstimate | None:
        """Reject a worker operation attempted in the API process."""
        raise GenerationProviderError("Generation Jobs must run in the private worker.")

    def synthesize(self, request: EpisodeRequest) -> bytes:
        """Reject a worker operation attempted in the API process."""
        raise GenerationProviderError("Generation Jobs must run in the private worker.")

    def stitch(self, audio: bytes) -> Episode:
        """Reject a worker operation attempted in the API process."""
        raise GenerationProviderError("Generation Jobs must run in the private worker.")


def build_generation_job_service(
    settings: Settings, provider: GenerationProvider
) -> GenerationJobService:
    """Compose public and worker service dependencies around a supplied provider."""
    tables = AzureTableStorage(settings.storage_account_name)
    blobs = AzureBlobStorage(settings.storage_account_name)
    return GenerationJobService(
        repository=AzureGenerationJobRepository(tables),
        queue=AzureGenerationQueue(settings.storage_account_name),
        episode_store=CloudCompletedEpisodeStore(blobs=blobs, tables=tables),
        provider=provider,
        clock=SystemClock(),
        approved_user_subjects=settings.approved_user_subjects,
    )


def build_worker_provider(settings: Settings) -> CloudGenerationProvider:
    """Compose external Article, Script, and audio collaborators only in the worker process."""
    tables = AzureTableStorage(settings.storage_account_name)
    blobs = AzureBlobStorage(settings.storage_account_name)
    episode_store = CloudEpisodeStore(blobs=blobs, tables=tables)
    agent = Agent(
        name="Summary Script Writer",
        model=OpenAIChat(
            id=settings.azure_openai_deployment.strip(),
            api_key=settings.azure_openai_api_key,
            base_url=settings.azure_openai_base_url.strip(),
        ),
        instructions=[
            "Write only the requested conversational summary script.",
            "Use the supplied article text as the sole source of facts.",
        ],
    )
    provider = CloudGenerationProvider(
        article_retriever=FirecrawlArticleRetriever(settings.firecrawl_api_key),
        script_strategies={
            ScriptStrategy.SUMMARY: SummaryScriptStrategy(agent),
            ScriptStrategy.NARRATION: NarrationScriptStrategy(),
        },
        audio_synthesizer=ElevenLabsAudioSynthesizer(settings),
        episode_store=episode_store,
        audio_stitcher=FfmpegAudioStitcher(),
        audio_duration_probe=FfmpegAudioDurationProbe(),
        tts_character_cap=settings.tts_character_cap,
        narration_confirmation_threshold=settings.narration_confirmation_threshold,
        narration_characters_per_minute=settings.narration_characters_per_minute,
    )
    return provider


def create_api_app():
    """Create the production API application from runtime environment configuration."""
    settings = Settings.from_env()
    jwks_client = jwt.PyJWKClient(
        f"https://login.microsoftonline.com/{settings.entra_tenant_id}/discovery/v2.0/keys"
    )
    resolver = EntraIdentityResolver(
        tenant_id=settings.entra_tenant_id,
        audience=f"api://{settings.api_application_id_uri}",
        signing_key=lambda token: jwks_client.get_signing_key_from_jwt(token).key,
    )
    return create_app(build_generation_job_service(settings, ApiGenerationProvider()), resolver)


def run_worker() -> None:
    """Run the private Azure Storage Queue worker until its Container App stops it."""
    settings = Settings.from_env()
    service = build_generation_job_service(settings, build_worker_provider(settings))
    AzureQueueWorker(settings.storage_account_name, service.process).run()
