from datetime import UTC, datetime

from blog_to_podcast.cloud import (
    AzureGenerationJobRepository,
    CloudEpisodeStore,
    CloudGenerationProvider,
)
from blog_to_podcast.episodes import (
    Article,
    Episode,
    EpisodeRequest,
    NarrationEstimate,
    ScriptStrategy,
    Voice,
)
from blog_to_podcast.jobs import GenerationJob, GenerationJobStatus


class FakeBlobStorage:
    def __init__(self) -> None:
        self.blobs: dict[tuple[str, str], bytes] = {}

    def upload(self, container: str, name: str, content: bytes, content_type: str) -> None:
        self.blobs[container, name] = content

    def download(self, container: str, name: str) -> bytes:
        return self.blobs[container, name]


class FakeTableStorage:
    def __init__(self) -> None:
        self.entities: list[dict[str, object]] = []
        self._next_etag = 1

    def upsert(self, table: str, entity: dict[str, object]) -> None:
        saved = {key: value for key, value in entity.items() if key != "_etag"}
        saved["_etag"] = str(self._next_etag)
        self._next_etag += 1
        self.entities = [
            candidate
            for candidate in self.entities
            if (
                candidate["PartitionKey"],
                candidate["RowKey"],
            )
            != (saved["PartitionKey"], saved["RowKey"])
        ]
        self.entities.append(saved)

    def query(self, table: str, partition_key: str) -> list[dict[str, object]]:
        return [
            dict(entity) for entity in self.entities if entity["PartitionKey"] == partition_key
        ]

    def get(self, table: str, partition_key: str, row_key: str) -> dict[str, object] | None:
        return next(
            (
                dict(entity)
                for entity in self.entities
                if entity["PartitionKey"] == partition_key and entity["RowKey"] == row_key
            ),
            None,
        )

    def replace_if_unchanged(self, table: str, entity: dict[str, object]) -> bool:
        current = self.get(table, str(entity["PartitionKey"]), str(entity["RowKey"]))
        if current is None or current["_etag"] != entity.get("_etag"):
            return False
        self.upsert(table, entity)
        return True


class ChangingArticleRetriever:
    def __init__(self) -> None:
        self.article = Article(
            url="https://example.com/article",
            title="Article",
            text="First version",
            canonical_url="https://example.com/article",
            content_fingerprint="fingerprint-v1",
        )

    def retrieve(self, article: Article) -> Article:
        return self.article


class FakeSummaryStrategy:
    name = ScriptStrategy.SUMMARY

    def create_script(self, article: Article) -> str:
        return f"Script for {article.text}."


class FakeAudioSynthesizer:
    def synthesize(self, script: str, voice: Voice) -> bytes:
        return script.encode()


class RecordingAudioSynthesizer(FakeAudioSynthesizer):
    def __init__(self) -> None:
        self.scripts: list[str] = []

    def synthesize(self, script: str, voice: Voice) -> bytes:
        self.scripts.append(script)
        return super().synthesize(script, voice)


class FakeAudioStitcher:
    def __init__(self) -> None:
        self.chunks: list[bytes] = []

    def stitch(self, chunks: list[bytes]) -> bytes:
        self.chunks = chunks
        return b"stitched-" + b"-".join(chunks)


def _request() -> EpisodeRequest:
    return EpisodeRequest(
        article=Article(
            url="https://example.com/article",
            title="Article",
            text="Article text",
            canonical_url="https://example.com/article",
            content_fingerprint="fingerprint-v1",
        ),
        script_strategy=ScriptStrategy.SUMMARY,
        voice=Voice(id="voice"),
    )


def test_cloud_episode_store_retains_and_retrieves_complete_episode_artifacts() -> None:
    blobs = FakeBlobStorage()
    store = CloudEpisodeStore(blobs=blobs, tables=FakeTableStorage())
    request = _request()
    episode = Episode(
        article=request.article,
        script="A concise script.",
        audio=b"mp3-bytes",
        generated_at=datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
        audio_duration_seconds=12.5,
    )

    store.save(request, episode)

    restored = store.find(request, "fingerprint-v1")
    assert restored == episode
    assert list(blobs.blobs.values()) == [b"mp3-bytes", b"A concise script."]


def test_cloud_job_repository_persists_the_prepared_narration_request_and_estimate() -> None:
    tables = FakeTableStorage()
    repository = AzureGenerationJobRepository(tables)
    initial = GenerationJob(
        id="job-1",
        request=_request(),
        status=GenerationJobStatus.RETRIEVING,
        message="Retrieving the Article.",
        created_at=datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
    )
    prepared_request = EpisodeRequest(
        article=Article(
            url=initial.request.article.url,
            title="Retrieved Article",
            text="Retrieved Article text.",
            canonical_url=initial.request.article.url,
            content_fingerprint="retrieved-fingerprint",
        ),
        script_strategy=ScriptStrategy.NARRATION,
        voice=initial.request.voice,
    )
    estimate = NarrationEstimate(character_count=120, listening_minutes=0.1)
    repository.create(initial)

    awaiting_confirmation = repository.transition(
        initial.id,
        {GenerationJobStatus.RETRIEVING},
        GenerationJobStatus.AWAITING_CONFIRMATION,
        "Confirmation is required before synthesis.",
        initial.updated_at,
        request=prepared_request,
        narration_estimate=estimate,
    )

    assert awaiting_confirmation is not None
    assert awaiting_confirmation.request == prepared_request
    assert awaiting_confirmation.narration_estimate == estimate
    assert repository.get(initial.id) == awaiting_confirmation


def test_cloud_job_repository_does_not_overwrite_a_concurrent_cancellation() -> None:
    class CancellationRacingTable(FakeTableStorage):
        def __init__(self) -> None:
            super().__init__()
            self.repository: AzureGenerationJobRepository | None = None
            self.cancelled = False

        def replace_if_unchanged(self, table: str, entity: dict[str, object]) -> bool:
            if not self.cancelled:
                self.cancelled = True
                assert self.repository is not None
                self.repository.transition(
                    str(entity["RowKey"]),
                    {GenerationJobStatus.QUEUED},
                    GenerationJobStatus.CANCELLED,
                    "Episode generation cancelled.",
                    datetime(2026, 8, 19, 15, 1, tzinfo=UTC),
                )
            return super().replace_if_unchanged(table, entity)

    tables = CancellationRacingTable()
    repository = AzureGenerationJobRepository(tables)
    tables.repository = repository
    initial = GenerationJob(
        id="job-2",
        request=_request(),
        status=GenerationJobStatus.QUEUED,
        message="Episode request queued.",
        created_at=datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 19, 15, 0, tzinfo=UTC),
    )
    repository.create(initial)

    transition = repository.transition(
        initial.id,
        {GenerationJobStatus.QUEUED},
        GenerationJobStatus.RETRIEVING,
        "Retrieving the Article.",
        datetime(2026, 8, 19, 15, 1, tzinfo=UTC),
    )

    assert transition is None
    assert repository.get(initial.id).status is GenerationJobStatus.CANCELLED  # type: ignore[union-attr]


def test_cloud_episode_store_retains_changed_source_as_a_new_revision() -> None:
    store = CloudEpisodeStore(blobs=FakeBlobStorage(), tables=FakeTableStorage())
    original_request = _request()
    revised_article = Article(
        url=original_request.article.url,
        title=original_request.article.title,
        text="Updated article text",
        canonical_url=original_request.article.canonical_url,
        content_fingerprint="fingerprint-v2",
    )
    revised_request = EpisodeRequest(
        article=revised_article,
        script_strategy=original_request.script_strategy,
        voice=original_request.voice,
    )

    store.save(original_request, Episode(original_request.article, "v1", b"audio-v1"))
    store.save(revised_request, Episode(revised_article, "v2", b"audio-v2", revision=2))

    assert store.find(original_request, "fingerprint-v1").script == "v1"  # type: ignore[union-attr]
    assert store.find(revised_request, "fingerprint-v2").script == "v2"  # type: ignore[union-attr]
    assert store.next_revision(original_request) == 3


def test_cloud_provider_reuses_a_matching_source_and_retains_changed_source_revision() -> None:
    store = CloudEpisodeStore(blobs=FakeBlobStorage(), tables=FakeTableStorage())
    retriever = ChangingArticleRetriever()
    provider = CloudGenerationProvider(
        article_retriever=retriever,
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=store,
    )
    request = _request()

    first_request = provider.retrieve(request)
    first_episode = provider.stitch(provider.synthesize(first_request))
    matching_request = provider.retrieve(request)
    retriever.article = Article(
        url=request.article.url,
        title=request.article.title,
        text="Updated version",
        canonical_url=request.article.canonical_url,
        content_fingerprint="fingerprint-v2",
    )
    changed_request = provider.retrieve(request)
    assert provider.find_existing(changed_request) is None
    changed_episode = provider.stitch(provider.synthesize(changed_request))

    assert provider.find_existing(matching_request) == first_episode
    assert changed_episode.revision == 2
    assert changed_episode.revision_note == "The source article content changed since revision 1."


def test_cloud_narration_estimates_then_chunks_stitches_and_retains_one_episode() -> None:
    class NarrationStrategy:
        name = ScriptStrategy.NARRATION

        def create_script(self, article: Article) -> str:
            return "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."

    store = CloudEpisodeStore(blobs=FakeBlobStorage(), tables=FakeTableStorage())
    synthesizer = RecordingAudioSynthesizer()
    stitcher = FakeAudioStitcher()
    provider = CloudGenerationProvider(
        article_retriever=ChangingArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationStrategy()},
        audio_synthesizer=synthesizer,
        episode_store=store,
        audio_stitcher=stitcher,
        tts_character_cap=35,
        narration_confirmation_threshold=10,
        narration_characters_per_minute=10,
    )
    request = EpisodeRequest(
        article=Article(url="https://example.com/article"),
        script_strategy=ScriptStrategy.NARRATION,
        voice=Voice(id="voice"),
    )

    prepared = provider.retrieve(request)
    estimate = provider.confirmation_estimate(prepared)
    episode = provider.stitch(provider.synthesize(prepared))

    assert estimate is not None
    assert estimate.character_count == 53
    assert synthesizer.scripts == ["First paragraph.\n\nSecond paragraph.", "Third paragraph."]
    assert stitcher.chunks == [b"First paragraph.\n\nSecond paragraph.", b"Third paragraph."]
    assert episode.audio == b"stitched-First paragraph.\n\nSecond paragraph.-Third paragraph."
    assert provider.find_existing(prepared) == episode
