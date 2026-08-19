"""Durable Generation Job lifecycle and worker orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import uuid4

from blog_to_podcast.episodes import (
    Episode,
    EpisodeGenerationError,
    EpisodeRequest,
    NarrationEstimate,
)


class GenerationJobStatus(StrEnum):
    """Listener-visible states for a Generation Job."""

    QUEUED = "queued"
    RETRIEVING = "retrieving"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    SYNTHESIZING = "synthesizing"
    STITCHING = "stitching"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Identity:
    """Authenticated caller identity used for public API authorization."""

    subject: str
    kind: str
    roles: frozenset[str] = frozenset()

    @classmethod
    def user(cls, subject: str, roles: set[str] | None = None) -> Identity:
        """Create an Entra user identity."""
        return cls(subject=subject, kind="user", roles=frozenset(roles or set()))

    @classmethod
    def application(cls, subject: str, roles: set[str] | None = None) -> Identity:
        """Create an Entra application identity."""
        return cls(subject=subject, kind="application", roles=frozenset(roles or set()))

    @classmethod
    def worker(cls, subject: str) -> Identity:
        """Create a worker identity, which has no public API access."""
        return cls(subject=subject, kind="worker")


@dataclass(frozen=True)
class GenerationJob:
    """Durable request to produce one Episode."""

    id: str
    request: EpisodeRequest
    status: GenerationJobStatus
    message: str
    created_at: datetime
    updated_at: datetime
    confirmed: bool = False
    narration_estimate: NarrationEstimate | None = None


class GenerationJobRepository(Protocol):
    """Persists Generation Jobs durably."""

    def create(self, job: GenerationJob) -> GenerationJob:
        """Create a Generation Job."""

    def get(self, job_id: str) -> GenerationJob | None:
        """Return a Generation Job by identity."""

    def save(self, job: GenerationJob) -> GenerationJob:
        """Persist a changed Generation Job."""

    def transition(
        self,
        job_id: str,
        expected_statuses: set[GenerationJobStatus],
        status: GenerationJobStatus,
        message: str,
        updated_at: datetime,
        confirmed: bool | None = None,
        request: EpisodeRequest | None = None,
        narration_estimate: NarrationEstimate | None = None,
    ) -> GenerationJob | None:
        """Atomically transition a Job only when it remains in an expected status."""


class GenerationQueue(Protocol):
    """Delivers Generation Job identities to the worker."""

    def enqueue(self, job_id: str) -> None:
        """Queue a Generation Job for worker processing."""


class CompletedEpisodeStore(Protocol):
    """Persists and retrieves completed Episodes by Generation Job identity."""

    def save(self, job_id: str, episode: Episode) -> None:
        """Persist a completed Episode."""

    def get(self, job_id: str) -> Episode | None:
        """Return a completed Episode."""


class GenerationProvider(Protocol):
    """Performs the external work needed to generate an Episode."""

    def retrieve(self, request: EpisodeRequest) -> EpisodeRequest:
        """Retrieve and normalize an Article for generation."""

    def find_existing(self, request: EpisodeRequest) -> Episode | None:
        """Return a retained Episode when the request's identity already matches."""

    def confirmation_estimate(self, request: EpisodeRequest) -> NarrationEstimate | None:
        """Return the confirmation estimate required before synthesis, if any."""

    def synthesize(self, request: EpisodeRequest) -> bytes:
        """Synthesize audio for a prepared Episode Request."""

    def stitch(self, audio: bytes) -> Episode:
        """Create the completed Episode from synthesized audio."""


class Clock(Protocol):
    """Supplies the current time."""

    def now(self) -> datetime:
        """Return the current time."""


class AccessDeniedError(PermissionError):
    """Raised when an identity cannot use a public Generation Job operation."""


class GenerationJobNotFoundError(LookupError):
    """Raised when a Generation Job is absent."""


class InvalidJobTransitionError(ValueError):
    """Raised when an operation is not valid for a Job Status."""


class GenerationProviderError(RuntimeError):
    """Raised when an external generation provider fails safely."""


class GenerationJobService:
    """Coordinates public Generation Job operations and private worker processing."""

    _UI_ROLE = "Episodes.Access"

    def __init__(
        self,
        *,
        repository: GenerationJobRepository,
        queue: GenerationQueue,
        episode_store: CompletedEpisodeStore,
        provider: GenerationProvider,
        clock: Clock,
        approved_user_subjects: set[str],
    ) -> None:
        """Initialize the service with durable and external collaborators."""
        self._repository = repository
        self._queue = queue
        self._episode_store = episode_store
        self._provider = provider
        self._clock = clock
        self._approved_user_subjects = approved_user_subjects

    def submit(self, request: EpisodeRequest, identity: Identity) -> GenerationJob:
        """Create and queue a Generation Job for an authorized caller."""
        self._authorize(identity)
        now = self._clock.now()
        job = GenerationJob(
            id=str(uuid4()),
            request=request,
            status=GenerationJobStatus.QUEUED,
            message="Episode request queued.",
            created_at=now,
            updated_at=now,
        )
        created = self._repository.create(job)
        self._queue.enqueue(created.id)
        return created

    def get(self, job_id: str, identity: Identity) -> GenerationJob:
        """Return an authorized caller's Generation Job."""
        self._authorize(identity)
        return self._get(job_id)

    def confirm(self, job_id: str, identity: Identity) -> GenerationJob:
        """Requeue a Job after the listener confirms expensive generation."""
        self._authorize(identity)
        job = self._get(job_id)
        if job.status is not GenerationJobStatus.AWAITING_CONFIRMATION:
            raise InvalidJobTransitionError(
                f"Generation Job {job.id} is {job.status.value}, not awaiting confirmation."
            )
        confirmed = self._transition(
            job.id,
            {GenerationJobStatus.AWAITING_CONFIRMATION},
            status=GenerationJobStatus.QUEUED,
            message="Confirmation received; synthesis queued.",
            confirmed=True,
        )
        if confirmed is None:
            raise InvalidJobTransitionError(
                f"Generation Job {job.id} is no longer awaiting confirmation."
            )
        self._queue.enqueue(confirmed.id)
        return confirmed

    def cancel(self, job_id: str, identity: Identity) -> GenerationJob:
        """Cancel a Job only before synthesis begins."""
        self._authorize(identity)
        job = self._get(job_id)
        cancellable = {
            GenerationJobStatus.QUEUED,
            GenerationJobStatus.RETRIEVING,
            GenerationJobStatus.AWAITING_CONFIRMATION,
        }
        if job.status not in cancellable:
            raise InvalidJobTransitionError(
                f"Generation Job {job.id} cannot be cancelled after synthesis begins."
            )
        cancelled = self._transition(
            job.id,
            cancellable,
            status=GenerationJobStatus.CANCELLED,
            message="Episode generation cancelled.",
        )
        if cancelled is None:
            raise InvalidJobTransitionError(
                f"Generation Job {job.id} changed while its cancellation was requested."
            )
        return cancelled

    def episode(self, job_id: str, identity: Identity) -> Episode:
        """Return a completed Episode to an authorized caller."""
        self._authorize(identity)
        job = self._get(job_id)
        if job.status is not GenerationJobStatus.COMPLETED:
            raise InvalidJobTransitionError(f"Generation Job {job.id} is not completed.")
        episode = self._episode_store.get(job.id)
        if episode is None:
            raise GenerationJobNotFoundError(
                f"Completed Episode for Generation Job {job.id} is absent."
            )
        return episode

    def process(self, job_id: str) -> GenerationJob:
        """Perform queued Generation Job work from the private worker boundary."""
        job = self._get(job_id)
        if job.status is not GenerationJobStatus.QUEUED:
            raise InvalidJobTransitionError(
                f"Generation Job {job.id} is {job.status.value} and cannot be processed."
            )
        retrieving = self._transition(
            job.id,
            {GenerationJobStatus.QUEUED},
            status=GenerationJobStatus.RETRIEVING,
            message="Retrieving the Article.",
        )
        if retrieving is None:
            return self._get(job.id)
        try:
            existing_episode = self._provider.find_existing(retrieving.request)
            if existing_episode is not None:
                return self._complete_existing_episode(retrieving, existing_episode)
            prepared_request = (
                retrieving.request
                if retrieving.request.article.content_fingerprint
                else self._provider.retrieve(retrieving.request)
            )
            existing_episode = self._provider.find_existing(prepared_request)
            if existing_episode is not None:
                return self._complete_existing_episode(retrieving, existing_episode)
            narration_estimate = self._provider.confirmation_estimate(prepared_request)
            if narration_estimate is not None and not retrieving.confirmed:
                awaiting_confirmation = self._transition(
                    retrieving.id,
                    {GenerationJobStatus.RETRIEVING},
                    status=GenerationJobStatus.AWAITING_CONFIRMATION,
                    message=(
                        f"Narration contains {narration_estimate.character_count:,} characters and "
                        f"is estimated to take {narration_estimate.listening_minutes:.1f} minutes "
                        "to listen to. Confirm to begin synthesis."
                    ),
                    request=prepared_request,
                    narration_estimate=narration_estimate,
                )
                return awaiting_confirmation or self._get(retrieving.id)
            synthesizing = self._transition(
                retrieving.id,
                {GenerationJobStatus.RETRIEVING},
                status=GenerationJobStatus.SYNTHESIZING,
                message="Synthesizing Episode audio.",
            )
            if synthesizing is None:
                return self._get(retrieving.id)
            audio = self._provider.synthesize(prepared_request)
            stitching = self._transition(
                synthesizing.id,
                {GenerationJobStatus.SYNTHESIZING},
                status=GenerationJobStatus.STITCHING,
                message="Stitching Episode audio.",
            )
            if stitching is None:
                return self._get(synthesizing.id)
            episode = self._provider.stitch(audio)
            self._episode_store.save(stitching.id, episode)
            completed = self._transition(
                stitching.id,
                {GenerationJobStatus.STITCHING},
                status=GenerationJobStatus.COMPLETED,
                message="Episode is ready to listen to.",
            )
            return completed or self._get(stitching.id)
        except (EpisodeGenerationError, GenerationProviderError) as exc:
            failed = self._transition(
                retrieving.id,
                {
                    GenerationJobStatus.RETRIEVING,
                    GenerationJobStatus.SYNTHESIZING,
                    GenerationJobStatus.STITCHING,
                },
                status=GenerationJobStatus.FAILED,
                message=f"Episode generation failed: {exc}",
            )
            return failed or self._get(retrieving.id)

    def _authorize(self, identity: Identity) -> None:
        """Authorize approved users and the UI application role."""
        if identity.kind == "user" and identity.subject in self._approved_user_subjects:
            return
        if identity.kind == "application" and self._UI_ROLE in identity.roles:
            return
        raise AccessDeniedError("This identity cannot access the Episode API.")

    def _complete_existing_episode(self, job: GenerationJob, episode: Episode) -> GenerationJob:
        """Link a reused Episode to its Job and mark it ready to listen to."""
        self._episode_store.save(job.id, episode)
        completed = self._transition(
            job.id,
            {GenerationJobStatus.RETRIEVING},
            status=GenerationJobStatus.COMPLETED,
            message="Existing Episode is ready to listen to.",
        )
        return completed or self._get(job.id)

    def _get(self, job_id: str) -> GenerationJob:
        """Return a Job or raise the service's stable not-found error."""
        job = self._repository.get(job_id)
        if job is None:
            raise GenerationJobNotFoundError(f"Generation Job {job_id} was not found.")
        return job

    def _transition(
        self,
        job_id: str,
        expected_statuses: set[GenerationJobStatus],
        *,
        status: GenerationJobStatus,
        message: str,
        confirmed: bool | None = None,
        request: EpisodeRequest | None = None,
        narration_estimate: NarrationEstimate | None = None,
    ) -> GenerationJob | None:
        """Persist a listener-visible Job Status transition if it is still valid."""
        return self._repository.transition(
            job_id,
            expected_statuses,
            status,
            message,
            self._clock.now(),
            confirmed,
            request,
            narration_estimate,
        )
