from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from blog_to_podcast.api import create_app
from blog_to_podcast.episodes import Article, Episode, EpisodeRequest, ScriptStrategy, Voice
from blog_to_podcast.jobs import (
    AccessDeniedError,
    GenerationJobService,
    GenerationJobStatus,
    GenerationProviderError,
    Identity,
    InvalidJobTransitionError,
)


class FakeRepository:
    def __init__(self) -> None:
        self.jobs = {}

    def create(self, job):
        self.jobs[job.id] = job
        return job

    def get(self, job_id):
        return self.jobs.get(job_id)

    def save(self, job):
        self.jobs[job.id] = job
        return job

    def transition(self, job_id, expected_statuses, status, message, updated_at, confirmed=None):
        job = self.jobs.get(job_id)
        if job is None or job.status not in expected_statuses:
            return None
        updated = job.__class__(
            id=job.id,
            request=job.request,
            status=status,
            message=message,
            created_at=job.created_at,
            updated_at=updated_at,
            confirmed=job.confirmed if confirmed is None else confirmed,
        )
        self.jobs[job_id] = updated
        return updated


class FakeQueue:
    def __init__(self) -> None:
        self.job_ids = []

    def enqueue(self, job_id):
        self.job_ids.append(job_id)


class FakeEpisodeStore:
    def __init__(self) -> None:
        self.episodes = {}

    def save(self, job_id, episode):
        self.episodes[job_id] = episode

    def get(self, job_id):
        return self.episodes.get(job_id)


class FakeProvider:
    def retrieve(self, request):
        return request

    def find_existing(self, request):
        return None

    def requires_confirmation(self, request):
        return request.script_strategy is ScriptStrategy.NARRATION

    def synthesize(self, request):
        return b"audio"

    def stitch(self, audio):
        return Episode(article=_article(), script="A script.", audio=audio)


class FakeClock:
    def now(self):
        return datetime(2026, 8, 19, 15, 0, tzinfo=UTC)


def _article() -> Article:
    return Article(url="https://example.com/article")


def _request(strategy: ScriptStrategy = ScriptStrategy.SUMMARY) -> EpisodeRequest:
    return EpisodeRequest(
        article=_article(),
        script_strategy=strategy,
        voice=Voice(id="voice"),
    )


def _service(
    provider: FakeProvider | None = None,
) -> tuple[GenerationJobService, FakeQueue, FakeEpisodeStore]:
    queue = FakeQueue()
    store = FakeEpisodeStore()
    return (
        GenerationJobService(
            repository=FakeRepository(),
            queue=queue,
            episode_store=store,
            provider=provider or FakeProvider(),
            clock=FakeClock(),
            approved_user_subjects={"owner"},
        ),
        queue,
        store,
    )


def test_submitting_an_episode_request_creates_a_queued_generation_job() -> None:
    service, queue, _ = _service()

    job = service.submit(_request(), Identity.user("owner"))

    assert job.status is GenerationJobStatus.QUEUED
    assert job.message == "Episode request queued."
    assert queue.job_ids == [job.id]


def test_narration_job_waits_for_confirmation_then_completes() -> None:
    service, queue, store = _service()
    job = service.submit(_request(ScriptStrategy.NARRATION), Identity.user("owner"))

    awaiting_confirmation = service.process(job.id)
    confirmed = service.confirm(job.id, Identity.user("owner"))
    completed = service.process(confirmed.id)

    assert awaiting_confirmation.status is GenerationJobStatus.AWAITING_CONFIRMATION
    assert completed.status is GenerationJobStatus.COMPLETED
    assert store.get(job.id) == Episode(article=_article(), script="A script.", audio=b"audio")
    assert queue.job_ids == [job.id, job.id]


def test_cancelling_before_synthesis_prevents_worker_processing() -> None:
    service, _, _ = _service()
    job = service.submit(_request(), Identity.user("owner"))

    cancelled = service.cancel(job.id, Identity.user("owner"))

    assert cancelled.status is GenerationJobStatus.CANCELLED
    with pytest.raises(InvalidJobTransitionError, match="cancelled"):
        service.process(job.id)


def test_cancelling_during_retrieval_prevents_synthesis() -> None:
    class CancellingProvider(FakeProvider):
        def __init__(self) -> None:
            self.service = None
            self.job_id = ""

        def retrieve(self, request):
            self.service.cancel(self.job_id, Identity.user("owner"))
            return request

    provider = CancellingProvider()
    service, _, _ = _service(provider)
    job = service.submit(_request(), Identity.user("owner"))
    provider.service = service
    provider.job_id = job.id

    result = service.process(job.id)

    assert result.status is GenerationJobStatus.CANCELLED


def test_provider_failure_marks_job_as_failed() -> None:
    class FailingProvider(FakeProvider):
        def retrieve(self, request):
            raise GenerationProviderError("Article is unavailable.")

    service, _, _ = _service(FailingProvider())
    job = service.submit(_request(), Identity.user("owner"))

    result = service.process(job.id)

    assert result.status is GenerationJobStatus.FAILED
    assert result.message == "Episode generation failed: Article is unavailable."


def test_worker_reuses_a_matching_episode_without_synthesizing() -> None:
    class ReusingProvider(FakeProvider):
        def __init__(self) -> None:
            self.synthesis_calls = 0
            self.episode = Episode(
                article=_article(), script="Existing script.", audio=b"existing-audio"
            )

        def find_existing(self, request):
            return self.episode

        def synthesize(self, request):
            self.synthesis_calls += 1
            return super().synthesize(request)

    provider = ReusingProvider()
    service, _, store = _service(provider)
    job = service.submit(_request(), Identity.user("owner"))

    completed = service.process(job.id)

    assert completed.status is GenerationJobStatus.COMPLETED
    assert store.get(job.id) == provider.episode
    assert provider.synthesis_calls == 0


def test_worker_identity_cannot_use_public_job_operations() -> None:
    service, _, _ = _service()

    with pytest.raises(AccessDeniedError):
        service.submit(_request(), Identity.worker("worker"))


def test_ui_application_role_can_submit_but_unapproved_user_cannot() -> None:
    service, _, _ = _service()

    app_job = service.submit(_request(), Identity.application("ui", {"Episodes.Access"}))

    assert app_job.status is GenerationJobStatus.QUEUED
    with pytest.raises(AccessDeniedError):
        service.submit(_request(), Identity.user("unapproved"))


class FakeIdentityResolver:
    def resolve(self, authorization):
        if authorization == "Bearer owner-token":
            return Identity.user("owner")
        raise AccessDeniedError("A valid Entra token is required.")


def test_api_returns_accepted_job_and_a_pollable_status_url() -> None:
    service, _, _ = _service()
    client = TestClient(create_app(service, FakeIdentityResolver()))

    response = client.post(
        "/v1/generation-jobs",
        headers={"Authorization": "Bearer owner-token"},
        json={
            "article_url": "https://example.com/article",
            "script_strategy": "summary",
            "voice_id": "voice",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert body["message"] == "Episode request queued."
    poll = client.get(body["status_url"], headers={"Authorization": "Bearer owner-token"})
    assert poll.status_code == 200
