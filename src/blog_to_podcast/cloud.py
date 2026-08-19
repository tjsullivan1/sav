"""Azure-backed persistence adapters for cloud Episode generation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Protocol

from azure.data.tables import TableServiceClient
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.storage.queue import QueueClient, QueueServiceClient

from blog_to_podcast.episodes import (
    Article,
    ArticleRetrievalError,
    ArticleRetriever,
    AudioDurationProbe,
    AudioStitcher,
    AudioStitchingError,
    AudioSynthesizer,
    Episode,
    EpisodeGenerationError,
    EpisodeRequest,
    EpisodeScriptStrategy,
    EpisodeStore,
    NarrationEstimate,
    ScriptCreationError,
    ScriptStrategy,
    Voice,
    split_script_at_paragraph_boundaries,
)
from blog_to_podcast.jobs import (
    GenerationJob,
    GenerationJobStatus,
    GenerationProviderError,
)
from blog_to_podcast.tts import AudioGenerationError


class BlobStorage(Protocol):
    """Stores private Episode artifacts as named blobs."""

    def upload(self, container: str, name: str, content: bytes, content_type: str) -> None:
        """Upload an artifact, replacing the same name if necessary."""

    def download(self, container: str, name: str) -> bytes:
        """Return an artifact's raw content."""


class TableStorage(Protocol):
    """Stores Episode indexes and metadata entities."""

    def upsert(self, table: str, entity: dict[str, object]) -> None:
        """Create or replace an entity."""

    def query(self, table: str, partition_key: str) -> list[dict[str, object]]:
        """Return entities in a partition."""


class AzureBlobStorage:
    """Blob Storage adapter authenticated with the workload identity."""

    def __init__(self, account_name: str) -> None:
        """Configure the adapter for an Azure Storage account."""
        self._client = BlobServiceClient(
            account_url=f"https://{account_name}.blob.core.windows.net",
            credential=DefaultAzureCredential(),
        )

    def upload(self, container: str, name: str, content: bytes, content_type: str) -> None:
        """Upload a private binary or text artifact."""
        self._client.get_blob_client(container, name).upload_blob(
            content,
            overwrite=True,
            content_settings=ContentSettings(content_type=content_type),
        )

    def download(self, container: str, name: str) -> bytes:
        """Download a complete artifact."""
        return self._client.get_blob_client(container, name).download_blob().readall()


class AzureTableStorage:
    """Table Storage adapter authenticated with the workload identity."""

    def __init__(self, account_name: str) -> None:
        """Configure the adapter for an Azure Storage account."""
        self._client = TableServiceClient(
            endpoint=f"https://{account_name}.table.core.windows.net",
            credential=DefaultAzureCredential(),
        )

    def upsert(self, table: str, entity: dict[str, object]) -> None:
        """Create or replace a table entity."""
        self._client.get_table_client(table).upsert_entity(entity=entity)

    def query(self, table: str, partition_key: str) -> list[dict[str, object]]:
        """Return an entity partition as ordinary dictionaries."""
        entities = self._client.get_table_client(table).query_entities(
            query_filter=f"PartitionKey eq '{partition_key}'"
        )
        return [dict(entity) for entity in entities]


class AzureGenerationQueue:
    """Storage Queue producer used by the public API."""

    def __init__(self, account_name: str, queue_name: str = "generation-jobs") -> None:
        """Configure the queue client for the workload identity."""
        self._client = QueueClient(
            account_url=f"https://{account_name}.queue.core.windows.net",
            queue_name=queue_name,
            credential=DefaultAzureCredential(),
        )

    def enqueue(self, job_id: str) -> None:
        """Queue a Generation Job identity for the private worker."""
        self._client.send_message(job_id)


class AzureGenerationJobRepository:
    """Table Storage repository for durable Generation Job lifecycle state."""

    _TABLE = "GenerationJobs"
    _PARTITION = "jobs"

    def __init__(self, tables: TableStorage) -> None:
        """Initialize the repository with the cloud table adapter."""
        self._tables = tables

    def create(self, job: GenerationJob) -> GenerationJob:
        """Persist a newly submitted Generation Job."""
        self._tables.upsert(self._TABLE, self._entity(job))
        return job

    def get(self, job_id: str) -> GenerationJob | None:
        """Return a Generation Job when it exists."""
        entities = self._tables.query(self._TABLE, self._PARTITION)
        for entity in entities:
            if entity["RowKey"] == job_id:
                return self._job(entity)
        return None

    def save(self, job: GenerationJob) -> GenerationJob:
        """Persist a full Generation Job replacement."""
        self._tables.upsert(self._TABLE, self._entity(job))
        return job

    def transition(
        self,
        job_id: str,
        expected_statuses: set[GenerationJobStatus],
        status: GenerationJobStatus,
        message: str,
        updated_at: datetime,
        confirmed: bool | None = None,
    ) -> GenerationJob | None:
        """Persist a valid lifecycle transition."""
        job = self.get(job_id)
        if job is None or job.status not in expected_statuses:
            return None
        updated = replace(
            job,
            status=status,
            message=message,
            updated_at=updated_at,
            confirmed=job.confirmed if confirmed is None else confirmed,
        )
        return self.save(updated)

    @classmethod
    def _entity(cls, job: GenerationJob) -> dict[str, object]:
        return {
            "PartitionKey": cls._PARTITION,
            "RowKey": job.id,
            "request": json.dumps(
                {
                    "article": asdict(job.request.article),
                    "script_strategy": job.request.script_strategy.value,
                    "voice": asdict(job.request.voice),
                    "refresh_source": job.request.refresh_source,
                    "narration_confirmed": job.request.narration_confirmed,
                },
                sort_keys=True,
            ),
            "status": job.status.value,
            "message": job.message,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "confirmed": job.confirmed,
            "narration_estimate": (
                asdict(job.narration_estimate) if job.narration_estimate is not None else None
            ),
        }

    @staticmethod
    def _job(entity: dict[str, object]) -> GenerationJob:
        request_data = json.loads(str(entity["request"]))
        return GenerationJob(
            id=str(entity["RowKey"]),
            request=EpisodeRequest(
                article=Article(**request_data["article"]),
                script_strategy=ScriptStrategy(request_data["script_strategy"]),
                voice=Voice(**request_data["voice"]),
                refresh_source=bool(request_data["refresh_source"]),
                narration_confirmed=bool(request_data["narration_confirmed"]),
            ),
            status=GenerationJobStatus(str(entity["status"])),
            message=str(entity["message"]),
            created_at=datetime.fromisoformat(str(entity["created_at"])),
            updated_at=datetime.fromisoformat(str(entity["updated_at"])),
            confirmed=bool(entity["confirmed"]),
            narration_estimate=(
                NarrationEstimate(**dict(entity["narration_estimate"]))
                if entity.get("narration_estimate") is not None
                else None
            ),
        )


class CloudCompletedEpisodeStore:
    """Links completed Generation Jobs to private cloud Episode artifacts."""

    _TABLE = "Episodes"
    _PARTITION = "completed-jobs"

    def __init__(self, *, blobs: BlobStorage, tables: TableStorage) -> None:
        """Initialize the job retrieval store."""
        self._blobs = blobs
        self._tables = tables

    def save(self, job_id: str, episode: Episode) -> None:
        """Persist the completed Episode under its authorized Generation Job."""
        audio_name = f"jobs/{job_id}.mp3"
        script_name = f"jobs/{job_id}.txt"
        self._blobs.upload("episodes", audio_name, episode.audio, "audio/mpeg")
        self._blobs.upload(
            "scripts", script_name, episode.script.encode(), "text/plain; charset=utf-8"
        )
        self._tables.upsert(
            self._TABLE,
            {
                "PartitionKey": self._PARTITION,
                "RowKey": job_id,
                "article": json.dumps(asdict(episode.article), sort_keys=True),
                "audio_name": audio_name,
                "script_name": script_name,
                "revision": episode.revision,
                "generated_at": (episode.generated_at or datetime.now(UTC)).isoformat(),
                "revision_note": episode.revision_note,
                "audio_duration_seconds": episode.audio_duration_seconds,
                "source_title": episode.source_title,
            },
        )

    def get(self, job_id: str) -> Episode | None:
        """Return a completed Episode by its authenticated Generation Job identity."""
        matches = self._tables.query(self._TABLE, self._PARTITION)
        entity = next((candidate for candidate in matches if candidate["RowKey"] == job_id), None)
        if entity is None:
            return None
        return Episode(
            article=Article(**json.loads(str(entity["article"]))),
            script=self._blobs.download("scripts", str(entity["script_name"])).decode(),
            audio=self._blobs.download("episodes", str(entity["audio_name"])),
            revision=int(entity["revision"]),
            generated_at=datetime.fromisoformat(str(entity["generated_at"])),
            revision_note=str(entity["revision_note"]),
            audio_duration_seconds=CloudEpisodeStore._float_or_none(
                entity["audio_duration_seconds"]
            ),
            source_title=str(entity["source_title"]),
        )


class CloudGenerationProvider:
    """Generation Provider using existing collaborators with cloud storage."""

    def __init__(
        self,
        *,
        article_retriever: ArticleRetriever,
        script_strategies: dict[ScriptStrategy, EpisodeScriptStrategy],
        audio_synthesizer: AudioSynthesizer,
        episode_store: EpisodeStore,
        audio_stitcher: AudioStitcher | None = None,
        audio_duration_probe: AudioDurationProbe | None = None,
        tts_character_cap: int = 5000,
        narration_confirmation_threshold: int = 10000,
        narration_characters_per_minute: int = 900,
    ) -> None:
        """Initialize a private worker provider from external generation collaborators."""
        self._article_retriever = article_retriever
        self._script_strategies = script_strategies
        self._audio_synthesizer = audio_synthesizer
        self._episode_store = episode_store
        self._audio_stitcher = audio_stitcher
        self._audio_duration_probe = audio_duration_probe
        self._tts_character_cap = tts_character_cap
        self._narration_confirmation_threshold = narration_confirmation_threshold
        self._narration_characters_per_minute = narration_characters_per_minute
        self._pending: dict[bytes, tuple[EpisodeRequest, str]] = {}

    def retrieve(self, request: EpisodeRequest) -> EpisodeRequest:
        """Retrieve source content only when a matching Episode was not already retained."""
        try:
            return replace(request, article=self._article_retriever.retrieve(request.article))
        except ArticleRetrievalError as exc:
            raise GenerationProviderError("Could not retrieve the Article.") from exc

    def find_existing(self, request: EpisodeRequest) -> Episode | None:
        """Find an existing Episode without calling a generation provider."""
        try:
            if request.article.content_fingerprint:
                return self._episode_store.find(request, request.article.content_fingerprint)
        except OSError as exc:
            raise GenerationProviderError("Could not access the cloud Episode Store.") from exc
        return None

    def confirmation_estimate(self, request: EpisodeRequest) -> NarrationEstimate | None:
        """Estimate retrieved Narration before expensive audio synthesis."""
        if request.script_strategy is not ScriptStrategy.NARRATION:
            return None
        strategy = self._script_strategies.get(request.script_strategy)
        if strategy is None:
            raise GenerationProviderError(
                f"No Script Strategy is configured for '{request.script_strategy.value}'."
            )
        try:
            script = strategy.create_script(request.article)
        except ScriptCreationError as exc:
            raise GenerationProviderError("Could not prepare the Narration script.") from exc
        if len(script) <= self._narration_confirmation_threshold:
            return None
        return NarrationEstimate(
            character_count=len(script),
            listening_minutes=len(script) / self._narration_characters_per_minute,
        )

    def synthesize(self, request: EpisodeRequest) -> bytes:
        """Create audio from the configured Script Strategy and retain context for stitching."""
        strategy = self._script_strategies.get(request.script_strategy)
        if strategy is None:
            raise GenerationProviderError(
                f"No Script Strategy is configured for '{request.script_strategy.value}'."
            )
        try:
            script = strategy.create_script(request.article)
            chunks = split_script_at_paragraph_boundaries(script, self._tts_character_cap)
            audio_chunks = [
                self._audio_synthesizer.synthesize(chunk, request.voice) for chunk in chunks
            ]
            audio = (
                self._audio_stitcher.stitch(audio_chunks)
                if self._audio_stitcher is not None
                else b"".join(audio_chunks)
            )
        except (AudioGenerationError, AudioStitchingError, ScriptCreationError, ValueError) as exc:
            raise GenerationProviderError("Could not generate Episode audio.") from exc
        if not audio:
            raise GenerationProviderError("Audio synthesis returned no playable audio.")
        self._pending[audio] = (request, script)
        return audio

    def stitch(self, audio: bytes) -> Episode:
        """Persist a newly generated Episode revision after audio is complete."""
        request, script = self._pending.pop(audio)
        try:
            revision = self._episode_store.next_revision(request)
            article = request.article
            source_title = article.title
            revision_note = ""
            if revision > 1:
                article = replace(
                    article,
                    title=(
                        f"UPDATED CONTENT \N{EM DASH} {article.title} "
                        f"(revision {revision}, {datetime.now(UTC).date().isoformat()})"
                    ),
                )
                revision_note = f"The source article content changed since revision {revision - 1}."
            duration = (
                self._audio_duration_probe.duration_seconds(audio)
                if self._audio_duration_probe is not None
                else None
            )
            episode = Episode(
                article=article,
                script=script,
                audio=audio,
                revision=revision,
                generated_at=datetime.now(UTC),
                revision_note=revision_note,
                audio_duration_seconds=duration,
                source_title=source_title,
            )
            self._episode_store.save(request, episode)
            return episode
        except (AudioStitchingError, EpisodeGenerationError, OSError) as exc:
            raise GenerationProviderError("Could not retain the generated Episode.") from exc


class AzureQueueWorker:
    """Long-running private Storage Queue worker for immutable application images."""

    def __init__(
        self,
        account_name: str,
        process_job: Callable[[str], object],
        queue_name: str = "generation-jobs",
    ) -> None:
        """Configure private queue consumption with a job-processing callable."""
        self._client = QueueServiceClient(
            account_url=f"https://{account_name}.queue.core.windows.net",
            credential=DefaultAzureCredential(),
        ).get_queue_client(queue_name)
        self._process_job = process_job

    def run(self) -> None:
        """Process queue messages until the Container App terminates the replica."""
        while True:
            messages = self._client.receive_messages(messages_per_page=1, visibility_timeout=300)
            for message in messages:
                self._process_job(message.content)
                self._client.delete_message(message.id, message.pop_receipt)


class CloudEpisodeStore:
    """Episode Store retaining private audio, scripts, and revision metadata in Azure Storage."""

    _TABLE = "Episodes"
    _AUDIO_CONTAINER = "episodes"
    _SCRIPT_CONTAINER = "scripts"

    def __init__(
        self,
        *,
        blobs: BlobStorage,
        tables: TableStorage,
        generation_version: str = "episode-v2",
    ) -> None:
        """Initialize the store with Blob and Table Storage collaborators."""
        self._blobs = blobs
        self._tables = tables
        self._generation_version = generation_version

    def find(self, request: EpisodeRequest, content_fingerprint: str) -> Episode | None:
        """Return an exact request and normalized-content match."""
        for entity in self._entities(request):
            if (
                entity["fingerprint"] == content_fingerprint
                and entity["request"] == self._request_key(request)
                and entity["generation_version"] == self._generation_version
                and entity["failure_state"] == ""
            ):
                return self._episode(entity)
        return None

    def find_latest(self, request: EpisodeRequest) -> Episode | None:
        """Return the latest successful retained revision for an Episode Request."""
        matches = [
            entity
            for entity in self._entities(request)
            if entity["request"] == self._request_key(request)
            and entity["generation_version"] == self._generation_version
            and entity["failure_state"] == ""
        ]
        if not matches:
            return None
        return self._episode(max(matches, key=lambda entity: str(entity["generated_at"])))

    def next_revision(self, request: EpisodeRequest) -> int:
        """Return the next revision number for a source and generation request."""
        revisions = [
            int(entity["revision"])
            for entity in self._entities(request)
            if entity["request"] == self._request_key(request)
            and entity["generation_version"] == self._generation_version
            and entity["failure_state"] == ""
        ]
        return max(revisions, default=0) + 1

    def save(self, request: EpisodeRequest, episode: Episode) -> None:
        """Persist a generated Episode and every artifact required to retrieve it."""
        generated_at = episode.generated_at or datetime.now(UTC)
        record_id = self._record_id(request, episode.article.content_fingerprint, episode.revision)
        audio_name = f"{record_id}.mp3"
        script_name = f"{record_id}.txt"
        self._blobs.upload(self._AUDIO_CONTAINER, audio_name, episode.audio, "audio/mpeg")
        self._blobs.upload(
            self._SCRIPT_CONTAINER,
            script_name,
            episode.script.encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        self._tables.upsert(
            self._TABLE,
            {
                "PartitionKey": self._source_identity(request.article),
                "RowKey": record_id,
                "fingerprint": episode.article.content_fingerprint,
                "request": self._request_key(request),
                "generation_version": self._generation_version,
                "revision": episode.revision,
                "generated_at": generated_at.isoformat(),
                "revision_note": episode.revision_note,
                "source_title": episode.source_title,
                "article": json.dumps(asdict(episode.article), sort_keys=True),
                "audio_name": audio_name,
                "script_name": script_name,
                "audio_duration_seconds": episode.audio_duration_seconds,
                "failure_state": "",
            },
        )

    def record_failure(self, request: EpisodeRequest, failure_state: str) -> None:
        """Record a terminal generation failure without creating Episode artifacts."""
        timestamp = datetime.now(UTC)
        self._tables.upsert(
            self._TABLE,
            {
                "PartitionKey": self._source_identity(request.article),
                "RowKey": hashlib.sha256(timestamp.isoformat().encode()).hexdigest(),
                "fingerprint": request.article.content_fingerprint,
                "request": self._request_key(request),
                "generation_version": self._generation_version,
                "revision": 0,
                "generated_at": timestamp.isoformat(),
                "revision_note": "",
                "source_title": request.article.title,
                "article": json.dumps(asdict(request.article), sort_keys=True),
                "audio_name": "",
                "script_name": "",
                "audio_duration_seconds": None,
                "failure_state": failure_state,
            },
        )

    def _entities(self, request: EpisodeRequest) -> list[dict[str, object]]:
        return self._tables.query(self._TABLE, self._source_identity(request.article))

    def _episode(self, entity: dict[str, object]) -> Episode:
        article = Article(**json.loads(str(entity["article"])))
        script = self._blobs.download(self._SCRIPT_CONTAINER, str(entity["script_name"])).decode(
            "utf-8"
        )
        return Episode(
            article=article,
            script=script,
            audio=self._blobs.download(self._AUDIO_CONTAINER, str(entity["audio_name"])),
            revision=int(entity["revision"]),
            generated_at=datetime.fromisoformat(str(entity["generated_at"])),
            revision_note=str(entity["revision_note"]),
            audio_duration_seconds=self._float_or_none(entity["audio_duration_seconds"]),
            source_title=str(entity["source_title"]),
        )

    @staticmethod
    def _float_or_none(value: object) -> float | None:
        return float(value) if value is not None else None

    @staticmethod
    def _source_identity(article: Article) -> str:
        return hashlib.sha256((article.canonical_url or article.url).encode("utf-8")).hexdigest()

    @staticmethod
    def _request_key(request: EpisodeRequest) -> str:
        return json.dumps(
            {
                "script_strategy": request.script_strategy.value,
                "voice": asdict(request.voice),
            },
            sort_keys=True,
        )

    def _record_id(self, request: EpisodeRequest, fingerprint: str, revision: int) -> str:
        return hashlib.sha256(
            (
                f"{self._source_identity(request.article)}:{self._request_key(request)}:"
                f"{fingerprint}:{revision}"
            ).encode()
        ).hexdigest()
