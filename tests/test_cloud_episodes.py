from datetime import UTC, datetime

from blog_to_podcast.cloud import CloudEpisodeStore, CloudGenerationProvider
from blog_to_podcast.episodes import Article, Episode, EpisodeRequest, ScriptStrategy, Voice


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

    def upsert(self, table: str, entity: dict[str, object]) -> None:
        self.entities = [
            candidate
            for candidate in self.entities
            if (
                candidate["PartitionKey"],
                candidate["RowKey"],
            )
            != (entity["PartitionKey"], entity["RowKey"])
        ]
        self.entities.append(entity)

    def query(self, table: str, partition_key: str) -> list[dict[str, object]]:
        return [entity for entity in self.entities if entity["PartitionKey"] == partition_key]


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
