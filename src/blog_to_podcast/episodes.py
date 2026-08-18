"""Core workflow and provider adapters for generating podcast episodes."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Protocol

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from elevenlabs import ElevenLabs
from firecrawl import Firecrawl
from firecrawl.v2.utils import FirecrawlError

from blog_to_podcast.config import MAX_SUMMARY_CHARS, Settings
from blog_to_podcast.tts import AudioGenerationError, text_to_speech

logger = logging.getLogger(__name__)
GENERATION_VERSION = "summary-v1"
_EPISODE_GENERATION_LOCK = Lock()


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
    refresh_source: bool = False


@dataclass(frozen=True)
class Episode:
    """The generated episode and its inspectable artifacts."""

    article: Article
    script: str
    audio: bytes
    revision: int = 1
    generated_at: datetime | None = None
    revision_note: str = ""


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


class EpisodeStore(Protocol):
    """Persists and retrieves generated episodes."""

    def find(self, request: EpisodeRequest, content_fingerprint: str) -> Episode | None:
        """Return an exact content and request match."""

    def find_latest(self, request: EpisodeRequest) -> Episode | None:
        """Return the latest episode for a source and generation request."""

    def next_revision(self, request: EpisodeRequest) -> int:
        """Return the revision number for new source content."""

    def save(self, request: EpisodeRequest, episode: Episode) -> None:
        """Persist a successfully generated episode."""

    def record_failure(self, request: EpisodeRequest, failure_state: str) -> None:
        """Persist the most recent failure metadata for a request."""


class LocalEpisodeStore:
    """A local filesystem Episode Store with Azure-ready episode metadata."""

    def __init__(self, directory: Path, generation_version: str = GENERATION_VERSION) -> None:
        """Initialize the store at a local directory."""
        self._directory = directory
        self._generation_version = generation_version

    def find(self, request: EpisodeRequest, content_fingerprint: str) -> Episode | None:
        """Return a matching stored episode for normalized article content."""
        for metadata_path in self._metadata_paths():
            metadata = self._read_metadata(metadata_path)
            if (
                metadata["source"]["identity"] == self._source_identity(request.article)
                and metadata["source"]["fingerprint"] == content_fingerprint
                and metadata["request"] == self._request_metadata(request)
                and metadata["generation_version"] == self._generation_version
                and metadata["failure_state"] is None
            ):
                return self._episode_from_metadata(metadata_path, metadata)
        return None

    def find_latest(self, request: EpisodeRequest) -> Episode | None:
        """Return the latest generated episode for a source request."""
        candidates: list[tuple[datetime, Path, dict[str, object]]] = []
        for metadata_path in self._metadata_paths():
            metadata = self._read_metadata(metadata_path)
            if (
                metadata["source"]["identity"] == self._source_identity(request.article)
                and metadata["request"] == self._request_metadata(request)
                and metadata["generation_version"] == self._generation_version
                and metadata["failure_state"] is None
            ):
                candidates.append(
                    (
                        datetime.fromisoformat(str(metadata["generated_at"])),
                        metadata_path,
                        metadata,
                    )
                )
        if not candidates:
            return None
        _, metadata_path, metadata = max(candidates, key=lambda candidate: candidate[0])
        return self._episode_from_metadata(metadata_path, metadata)

    def next_revision(self, request: EpisodeRequest) -> int:
        """Return the next retained revision number for a source request."""
        revisions: list[int] = []
        for path in self._metadata_paths():
            metadata = self._read_metadata(path)
            if (
                metadata["source"]["identity"] == self._source_identity(request.article)
                and metadata["request"] == self._request_metadata(request)
                and metadata["generation_version"] == self._generation_version
                and metadata["failure_state"] is None
            ):
                revisions.append(int(metadata["revision"]))
        return max(revisions, default=0) + 1

    def save(self, request: EpisodeRequest, episode: Episode) -> None:
        """Persist audio and the full metadata required to recreate an episode."""
        generated_at = episode.generated_at or datetime.now(UTC)
        record_id = self._record_id(request, episode.article.content_fingerprint, episode.revision)
        audio_path = self._directory / f"{record_id}.mp3"
        metadata_path = self._directory / f"{record_id}.json"
        self._directory.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(episode.audio)
        metadata = {
            "source": {
                "identity": self._source_identity(episode.article),
                "url": episode.article.url,
                "canonical_url": episode.article.canonical_url,
                "fingerprint": episode.article.content_fingerprint,
            },
            "request": self._request_metadata(request),
            "script": episode.script,
            "audio": {"path": audio_path.name, "format": "audio/mpeg", "bytes": len(episode.audio)},
            "generation_version": self._generation_version,
            "generated_at": generated_at.isoformat(),
            "revision": episode.revision,
            "revision_note": episode.revision_note,
            "article": asdict(episode.article),
            "failure_state": None,
        }
        metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")

    def record_failure(self, request: EpisodeRequest, failure_state: str) -> None:
        """Persist failure state without creating a playable episode."""
        self._directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC)
        record_id = hashlib.sha256(
            f"{self._source_identity(request.article)}:{timestamp.isoformat()}".encode()
        ).hexdigest()
        metadata = {
            "source": {
                "identity": self._source_identity(request.article),
                "url": request.article.url,
                "canonical_url": request.article.canonical_url,
                "fingerprint": request.article.content_fingerprint,
            },
            "request": self._request_metadata(request),
            "script": "",
            "audio": None,
            "generation_version": self._generation_version,
            "generated_at": timestamp.isoformat(),
            "revision": self.next_revision(request),
            "revision_note": "",
            "article": asdict(request.article),
            "failure_state": failure_state,
        }
        (self._directory / f"{record_id}.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _metadata_paths(self) -> list[Path]:
        """Return persisted episode metadata paths."""
        if not self._directory.exists():
            return []
        return list(self._directory.glob("*.json"))

    @staticmethod
    def _read_metadata(path: Path) -> dict[str, object]:
        """Read one episode metadata document."""
        return json.loads(path.read_text(encoding="utf-8"))

    def _episode_from_metadata(self, metadata_path: Path, metadata: dict[str, object]) -> Episode:
        """Hydrate an episode from its metadata and sibling audio file."""
        article = Article(**metadata["article"])
        audio_path = metadata_path.parent / metadata["audio"]["path"]
        return Episode(
            article=article,
            script=str(metadata["script"]),
            audio=audio_path.read_bytes(),
            revision=int(metadata["revision"]),
            generated_at=datetime.fromisoformat(str(metadata["generated_at"])),
            revision_note=str(metadata["revision_note"]),
        )

    @staticmethod
    def _source_identity(article: Article) -> str:
        """Return the stable source identity used across content revisions."""
        return article.url.strip()

    @staticmethod
    def _request_metadata(request: EpisodeRequest) -> dict[str, str]:
        """Return the request fields that affect generated output."""
        return {
            "script_strategy": request.script_strategy.value,
            "voice_id": request.voice.id,
            "voice_model_id": request.voice.model_id,
        }

    def _record_id(self, request: EpisodeRequest, fingerprint: str, revision: int) -> str:
        """Create a stable per-revision filename identifier."""
        key = (
            f"{self._source_identity(request.article)}:{fingerprint}:"
            f"{self._request_metadata(request)}:{self._generation_version}:{revision}"
        )
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class EpisodeGenerationWorkflow:
    """Generate episodes through retrieval, script creation, and synthesis."""

    def __init__(
        self,
        *,
        article_retriever: ArticleRetriever,
        script_strategies: dict[ScriptStrategy, EpisodeScriptStrategy],
        audio_synthesizer: AudioSynthesizer,
        episode_store: EpisodeStore,
    ) -> None:
        """Initialize the workflow with its external collaborators."""
        self._article_retriever = article_retriever
        self._script_strategies = script_strategies
        self._audio_synthesizer = audio_synthesizer
        self._episode_store = episode_store

    def generate(self, request: EpisodeRequest) -> Episode:
        """Generate a playable episode from a request."""
        with _EPISODE_GENERATION_LOCK:
            return self._generate(request)

    def _generate(self, request: EpisodeRequest) -> Episode:
        """Generate an episode while serializing local revision allocation."""
        if request.article.content_fingerprint:
            stored_episode = self._episode_store.find(request, request.article.content_fingerprint)
        elif not request.refresh_source:
            stored_episode = self._episode_store.find_latest(request)
        else:
            stored_episode = None
        if stored_episode is not None:
            return stored_episode

        try:
            if request.article.content_fingerprint:
                article = request.article
            else:
                article = self._article_retriever.retrieve(request.article)
        except ArticleRetrievalError as exc:
            self._episode_store.record_failure(request, "article_retrieval")
            raise EpisodeGenerationError(
                "Could not retrieve the article. Confirm the URL is public and available."
            ) from exc

        stored_episode = self._episode_store.find(request, article.content_fingerprint)
        if stored_episode is not None:
            return stored_episode

        strategy = self._script_strategies.get(request.script_strategy)
        if strategy is None:
            raise EpisodeGenerationError(
                f"No script strategy is configured for '{request.script_strategy}'."
            )

        try:
            script = strategy.create_script(article)
        except ScriptCreationError as exc:
            self._episode_store.record_failure(request, "script_creation")
            raise EpisodeGenerationError("Could not create the episode script.") from exc

        try:
            audio = self._audio_synthesizer.synthesize(script, request.voice)
        except AudioGenerationError as exc:
            self._episode_store.record_failure(request, "audio_synthesis")
            raise EpisodeGenerationError("Could not synthesize the episode audio.") from exc

        if not audio:
            self._episode_store.record_failure(request, "empty_audio")
            raise EpisodeGenerationError("Audio synthesis returned no playable audio.")
        revision = self._episode_store.next_revision(request)
        revision_note = ""
        if revision > 1:
            date = datetime.now(UTC).date().isoformat()
            article = Article(
                url=article.url,
                title=f"UPDATED CONTENT - Revision {revision} ({date}): {article.title}",
                text=article.text,
                canonical_url=article.canonical_url,
                content_fingerprint=article.content_fingerprint,
            )
            revision_note = f"The source article content changed since revision {revision - 1}."
        episode = Episode(
            article=article,
            script=script,
            audio=audio,
            revision=revision,
            generated_at=datetime.now(UTC),
            revision_note=revision_note,
        )
        self._episode_store.save(request, episode)
        return episode


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
        episode_store=LocalEpisodeStore(Path(".sav") / "episodes"),
    )


def generate_summary_episode(
    url: str, settings: Settings, *, refresh_source: bool = False
) -> Episode:
    """Generate a Summary Episode through the core workflow."""
    workflow = build_summary_episode_workflow(settings)
    return workflow.generate(
        EpisodeRequest(
            article=Article(url=url),
            script_strategy=ScriptStrategy.SUMMARY,
            voice=Voice(id=settings.voice_id, model_id=settings.tts_model_id),
            refresh_source=refresh_source,
        )
    )
