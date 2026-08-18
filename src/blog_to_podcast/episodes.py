"""Core workflow and provider adapters for generating podcast episodes."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from elevenlabs import ElevenLabs
from firecrawl import Firecrawl
from firecrawl.v2.utils import FirecrawlError

from blog_to_podcast.config import MAX_SUMMARY_CHARS, Settings
from blog_to_podcast.tts import AudioGenerationError, text_to_speech

logger = logging.getLogger(__name__)


class ScriptStrategy(StrEnum):
    """The available strategies for turning an article into a script."""

    SUMMARY = "summary"


@dataclass(frozen=True)
class Article:
    """Article input or retrieved article content."""

    url: str
    title: str = ""
    text: str = ""
    canonical_url: str = ""
    content_fingerprint: str = ""


@dataclass(frozen=True)
class Voice:
    """Voice configuration selected for an episode."""

    id: str
    model_id: str = "eleven_multilingual_v2"


@dataclass(frozen=True)
class EpisodeRequest:
    """Inputs for generating an episode without service credentials."""

    article: Article
    script_strategy: ScriptStrategy
    voice: Voice


@dataclass(frozen=True)
class Episode:
    """The generated episode and its inspectable artifacts."""

    article: Article
    script: str
    audio: bytes


class EpisodeGenerationError(RuntimeError):
    """Raised when an episode cannot be generated at a named workflow stage."""


class ArticleRetrievalError(RuntimeError):
    """Raised when an article cannot be retrieved as usable text."""


class ScriptCreationError(RuntimeError):
    """Raised when a script strategy cannot create a usable script."""


class ArticleRetriever(Protocol):
    """Retrieves normalized article content from an article source."""

    def retrieve(self, article: Article) -> Article:
        """Retrieve the article's normalized content."""


class EpisodeScriptStrategy(Protocol):
    """Creates a narration script from a retrieved article."""

    name: ScriptStrategy

    def create_script(self, article: Article) -> str:
        """Create an episode script."""


class AudioSynthesizer(Protocol):
    """Synthesizes playable audio from a narration script."""

    def synthesize(self, script: str, voice: Voice) -> bytes:
        """Create MP3 audio for the given voice."""


class EpisodeGenerationWorkflow:
    """Generate episodes through retrieval, script creation, and synthesis."""

    def __init__(
        self,
        *,
        article_retriever: ArticleRetriever,
        script_strategies: dict[ScriptStrategy, EpisodeScriptStrategy],
        audio_synthesizer: AudioSynthesizer,
    ) -> None:
        """Initialize the workflow with its external collaborators."""
        self._article_retriever = article_retriever
        self._script_strategies = script_strategies
        self._audio_synthesizer = audio_synthesizer

    def generate(self, request: EpisodeRequest) -> Episode:
        """Generate a playable episode from a request."""
        try:
            article = self._article_retriever.retrieve(request.article)
        except ArticleRetrievalError as exc:
            raise EpisodeGenerationError(
                "Could not retrieve the article. Confirm the URL is public and available."
            ) from exc

        strategy = self._script_strategies.get(request.script_strategy)
        if strategy is None:
            raise EpisodeGenerationError(
                f"No script strategy is configured for '{request.script_strategy}'."
            )

        try:
            script = strategy.create_script(article)
        except ScriptCreationError as exc:
            raise EpisodeGenerationError("Could not create the episode script.") from exc

        try:
            audio = self._audio_synthesizer.synthesize(script, request.voice)
        except AudioGenerationError as exc:
            raise EpisodeGenerationError("Could not synthesize the episode audio.") from exc

        if not audio:
            raise EpisodeGenerationError("Audio synthesis returned no playable audio.")
        return Episode(article=article, script=script, audio=audio)


class FirecrawlArticleRetriever:
    """Retrieve normalized article content through Firecrawl."""

    def __init__(self, api_key: str, client: Firecrawl | None = None) -> None:
        """Initialize the retriever with Firecrawl credentials or a client."""
        self._client = client or Firecrawl(api_key=api_key)

    def retrieve(self, article: Article) -> Article:
        """Retrieve article markdown and canonical metadata from Firecrawl."""
        try:
            document = self._client.scrape(
                article.url, formats=["markdown"], only_main_content=True
            )
        except FirecrawlError as exc:
            raise ArticleRetrievalError("Firecrawl could not retrieve the article.") from exc
        text = (document.markdown or "").strip()
        if not text:
            raise ArticleRetrievalError("Firecrawl returned no article text.")

        metadata = document.metadata_typed
        canonical_url = metadata.og_url or metadata.url or article.url
        title = metadata.title or canonical_url
        return Article(
            url=article.url,
            title=title.strip(),
            text=text,
            canonical_url=canonical_url.strip(),
            content_fingerprint=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


class SummaryScriptStrategy:
    """Create a conversational summary script through agno and Azure OpenAI."""

    name = ScriptStrategy.SUMMARY

    def __init__(self, agent: Agent) -> None:
        """Initialize the strategy with an agno summary-writing agent."""
        self._agent = agent

    def create_script(self, article: Article) -> str:
        """Rewrite a retrieved article as a concise conversational script."""
        response = self._agent.run(
            "Create a concise, engaging, conversational podcast summary "
            f"(maximum {MAX_SUMMARY_CHARS} characters) from this retrieved article. "
            "Capture its main points without adding information not present in the article.\n\n"
            f"Title: {article.title}\n"
            f"Canonical URL: {article.canonical_url}\n\n"
            f"Article:\n{article.text}"
        )
        script = (getattr(response, "content", None) or str(response or "")).strip()
        if not script:
            raise ScriptCreationError("The summary strategy returned an empty script.")
        return script


class ElevenLabsAudioSynthesizer:
    """Synthesize episode audio through ElevenLabs."""

    def __init__(self, settings: Settings, client: ElevenLabs | None = None) -> None:
        """Initialize the synthesizer with service configuration or a client."""
        self._settings = settings
        self._client = client

    def synthesize(self, script: str, voice: Voice) -> bytes:
        """Create MP3 audio using the voice selected in the request."""
        settings = self._settings.model_copy(
            update={"voice_id": voice.id, "tts_model_id": voice.model_id}
        )
        return text_to_speech(script, settings, client=self._client)


def build_summary_episode_workflow(settings: Settings) -> EpisodeGenerationWorkflow:
    """Build the configured workflow for a Summary Episode."""
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
    return EpisodeGenerationWorkflow(
        article_retriever=FirecrawlArticleRetriever(settings.firecrawl_api_key),
        script_strategies={ScriptStrategy.SUMMARY: SummaryScriptStrategy(agent)},
        audio_synthesizer=ElevenLabsAudioSynthesizer(settings),
    )


def generate_summary_episode(url: str, settings: Settings) -> Episode:
    """Generate a Summary Episode through the core workflow."""
    workflow = build_summary_episode_workflow(settings)
    return workflow.generate(
        EpisodeRequest(
            article=Article(url=url),
            script_strategy=ScriptStrategy.SUMMARY,
            voice=Voice(id=settings.voice_id, model_id=settings.tts_model_id),
        )
    )
