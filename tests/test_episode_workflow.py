import hashlib
import json
import re
from datetime import UTC, datetime

import pytest

from blog_to_podcast.episodes import (
    Article,
    ArticleRetrievalError,
    AudioStitchingError,
    Episode,
    EpisodeGenerationError,
    EpisodeGenerationWorkflow,
    EpisodeRequest,
    LocalEpisodeStore,
    NarrationConfirmationRequiredError,
    NarrationScriptStrategy,
    ScriptStrategy,
    Voice,
)


class FakeArticleRetriever:
    def retrieve(self, article: Article) -> Article:
        return Article(
            url=article.url,
            title="A useful article",
            text="Article body.",
            canonical_url="https://example.com/useful-article",
            content_fingerprint=hashlib.sha256(b"Article body.").hexdigest(),
        )


class FailingArticleRetriever:
    def retrieve(self, article: Article) -> Article:
        raise ArticleRetrievalError("source unavailable")


class FailingEpisodeStore:
    def find(self, request: EpisodeRequest, content_fingerprint: str) -> Episode | None:
        raise OSError("storage unavailable")

    def find_latest(self, request: EpisodeRequest) -> Episode | None:
        raise OSError("storage unavailable")

    def next_revision(self, request: EpisodeRequest) -> int:
        raise OSError("storage unavailable")

    def save(self, request: EpisodeRequest, episode: Episode) -> None:
        raise OSError("storage unavailable")

    def record_failure(self, request: EpisodeRequest, failure_state: str) -> None:
        raise OSError("storage unavailable")


class FakeSummaryScriptStrategy:
    name = ScriptStrategy.SUMMARY

    def create_script(self, article: Article) -> str:
        return f"Here is the summary of {article.title}."


class FakeAudioSynthesizer:
    def __init__(self) -> None:
        self.calls = 0

    def synthesize(self, script: str, voice: Voice) -> bytes:
        self.calls += 1
        return b"audio"


class RecordingAudioSynthesizer(FakeAudioSynthesizer):
    def __init__(self) -> None:
        super().__init__()
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


class FixedAudioDurationProbe:
    def duration_seconds(self, audio: bytes) -> float:
        assert audio == b"audio"
        return 42.5


class FailingAudioDurationProbe:
    def duration_seconds(self, audio: bytes) -> float:
        raise AudioStitchingError("duration unavailable")


class CountingArticleRetriever(FakeArticleRetriever):
    def __init__(self) -> None:
        self.calls = 0

    def retrieve(self, article: Article) -> Article:
        self.calls += 1
        return super().retrieve(article)


class CountingSummaryScriptStrategy(FakeSummaryScriptStrategy):
    def __init__(self) -> None:
        self.calls = 0

    def create_script(self, article: Article) -> str:
        self.calls += 1
        return super().create_script(article)


class CountingNarrationScriptStrategy(NarrationScriptStrategy):
    def __init__(self) -> None:
        self.calls = 0

    def create_script(self, article: Article) -> str:
        self.calls += 1
        return super().create_script(article)


def _request(article: Article | None = None) -> EpisodeRequest:
    return EpisodeRequest(
        article=article or Article(url="https://example.com/useful-article"),
        script_strategy=ScriptStrategy.SUMMARY,
        voice=Voice(id="host-voice"),
    )


def _narration_request(
    article: Article | None = None, *, narration_confirmed: bool = False
) -> EpisodeRequest:
    return EpisodeRequest(
        article=article or Article(url="https://example.com/useful-article"),
        script_strategy=ScriptStrategy.NARRATION,
        voice=Voice(id="host-voice"),
        narration_confirmed=narration_confirmed,
    )


def test_generates_and_persists_a_playable_summary_episode_from_an_episode_request(
    tmp_path,
) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=store,
    )

    episode = workflow.generate(_request())

    assert episode.audio == b"audio"
    assert episode.article.title == "A useful article"
    assert episode.script == "Here is the summary of A useful article."
    assert episode.article.content_fingerprint == hashlib.sha256(b"Article body.").hexdigest()
    assert store.find(_request(), episode.article.content_fingerprint) == episode


def test_reuses_a_matching_stored_episode_without_invoking_external_services(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    retriever = CountingArticleRetriever()
    strategy = CountingSummaryScriptStrategy()
    synthesizer = FakeAudioSynthesizer()
    workflow = EpisodeGenerationWorkflow(
        article_retriever=retriever,
        script_strategies={ScriptStrategy.SUMMARY: strategy},
        audio_synthesizer=synthesizer,
        episode_store=store,
    )

    first_episode = workflow.generate(_request())
    second_episode = workflow.generate(_request())

    assert second_episode == first_episode
    assert retriever.calls == 1
    assert strategy.calls == 1
    assert synthesizer.calls == 1


def test_retains_an_updated_content_revision_with_listener_context(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=store,
    )
    original = Article(
        url="https://example.com/useful-article",
        title="A useful article",
        text="Original article body.",
        canonical_url="https://example.com/useful-article",
        content_fingerprint=hashlib.sha256(b"Original article body.").hexdigest(),
    )
    revised = Article(
        url=original.url,
        title=original.title,
        text="Revised article body.",
        canonical_url=original.canonical_url,
        content_fingerprint=hashlib.sha256(b"Revised article body.").hexdigest(),
    )

    first_episode = workflow.generate(_request(original))
    revised_episode = workflow.generate(_request(revised))

    assert first_episode.revision == 1
    assert revised_episode.revision == 2
    assert re.fullmatch(
        r"UPDATED CONTENT \N{EM DASH} A useful article \(revision 2, \d{4}-\d{2}-\d{2}\)",
        revised_episode.article.title,
    )
    assert revised_episode.revision_note == "The source article content changed since revision 1."
    assert store.find(_request(original), original.content_fingerprint) == first_episode
    revised_metadata = next(
        json.loads(path.read_text(encoding="utf-8"))
        for path in (tmp_path / "episodes").glob("*.json")
        if json.loads(path.read_text(encoding="utf-8"))["revision"] == 2
    )
    assert revised_metadata["source"]["title"] == "A useful article"


def test_local_store_retains_required_episode_metadata(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    request = _request(
        Article(
            url="https://example.com/useful-article",
            title="A useful article",
            text="Article body.",
            canonical_url="https://example.com/useful-article",
            content_fingerprint="article-fingerprint",
        )
    )
    generated_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    store.save(
        request,
        Episode(
            article=request.article,
            script="A playable episode.",
            audio=b"audio",
            generated_at=generated_at,
            audio_duration_seconds=42.5,
        ),
    )

    metadata = json.loads(next((tmp_path / "episodes").glob("*.json")).read_text(encoding="utf-8"))

    assert metadata["source"]["title"] == "A useful article"
    assert metadata["source"]["first_seen_at"] == "2026-08-18T12:00:00+00:00"
    assert metadata["audio"]["format"] == "audio/mpeg"
    assert metadata["audio"]["duration_seconds"] == 42.5


def test_episode_positional_constructor_retains_existing_field_order() -> None:
    article = Article(url="https://example.com/article")
    generated_at = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)

    episode = Episode(article, "A script.", b"audio", 2, generated_at, "Updated source.")

    assert episode.revision == 2
    assert episode.generated_at == generated_at
    assert episode.revision_note == "Updated source."
    assert episode.audio_duration_seconds is None


def test_generating_an_episode_records_its_audio_duration(tmp_path) -> None:
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        audio_duration_probe=FixedAudioDurationProbe(),
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
    )

    episode = workflow.generate(_request())

    assert episode.audio_duration_seconds == 42.5


def test_reports_an_actionable_audio_duration_failure(tmp_path) -> None:
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        audio_duration_probe=FailingAudioDurationProbe(),
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
    )

    with pytest.raises(EpisodeGenerationError, match="measure the episode audio duration"):
        workflow.generate(_request())


def test_refreshing_unchanged_content_reuses_the_stored_episode(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    retriever = CountingArticleRetriever()
    strategy = CountingSummaryScriptStrategy()
    synthesizer = FakeAudioSynthesizer()
    workflow = EpisodeGenerationWorkflow(
        article_retriever=retriever,
        script_strategies={ScriptStrategy.SUMMARY: strategy},
        audio_synthesizer=synthesizer,
        episode_store=store,
    )

    first_episode = workflow.generate(_request())
    refreshed_episode = workflow.generate(
        EpisodeRequest(
            article=Article(url="https://example.com/useful-article"),
            script_strategy=ScriptStrategy.SUMMARY,
            voice=Voice(id="host-voice"),
            refresh_source=True,
        )
    )

    assert refreshed_episode == first_episode
    assert retriever.calls == 2
    assert strategy.calls == 1
    assert synthesizer.calls == 1


def test_reports_an_actionable_retrieval_failure(tmp_path) -> None:
    with pytest.raises(EpisodeGenerationError, match="retrieve the article"):
        EpisodeGenerationWorkflow(
            article_retriever=FailingArticleRetriever(),
            script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
            audio_synthesizer=FakeAudioSynthesizer(),
            episode_store=LocalEpisodeStore(tmp_path / "episodes"),
        ).generate(_request(Article(url="https://example.com/unavailable")))


def test_reports_an_actionable_episode_storage_failure() -> None:
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=FailingEpisodeStore(),
    )

    with pytest.raises(EpisodeGenerationError, match="episode storage"):
        workflow.generate(_request())


def test_narration_cleans_article_text_without_summarizing(tmp_path) -> None:
    article = Article(
        url="https://example.com/audio",
        title="Audio article",
        text=(
            "## Heading\n\nRead more at [Example](https://example.com). "
            "Keep `x > 0`, S_0, and 2 * 3.\n\nKeep this paragraph."
        ),
        canonical_url="https://example.com/audio",
        content_fingerprint=hashlib.sha256(b"audio").hexdigest(),
    )
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
    )

    episode = workflow.generate(_narration_request(article))

    assert episode.script == (
        "Heading\n\nRead more at Example. Keep x > 0, S_0, and 2 * 3.\n\nKeep this paragraph."
    )


def test_narration_splits_at_paragraph_boundaries_and_stitches_chunks(tmp_path) -> None:
    article = Article(
        url="https://example.com/long",
        title="Long article",
        text="First paragraph.\n\nSecond paragraph.\n\nThird paragraph.",
        canonical_url="https://example.com/long",
        content_fingerprint=hashlib.sha256(b"long").hexdigest(),
    )
    synthesizer = RecordingAudioSynthesizer()
    stitcher = FakeAudioStitcher()
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationScriptStrategy()},
        audio_synthesizer=synthesizer,
        audio_stitcher=stitcher,
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
        tts_character_cap=35,
    )

    episode = workflow.generate(_narration_request(article))

    assert synthesizer.scripts == ["First paragraph.\n\nSecond paragraph.", "Third paragraph."]
    assert stitcher.chunks == [b"audio", b"audio"]
    assert episode.audio == b"stitched-audio-audio"


def test_expensive_narration_requires_confirmation_before_audio_synthesis(tmp_path) -> None:
    article = Article(
        url="https://example.com/expensive",
        title="Expensive article",
        text="A sufficiently long article.",
        canonical_url="https://example.com/expensive",
        content_fingerprint=hashlib.sha256(b"expensive").hexdigest(),
    )
    synthesizer = FakeAudioSynthesizer()
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationScriptStrategy()},
        audio_synthesizer=synthesizer,
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
        narration_confirmation_threshold=10,
        narration_characters_per_minute=10,
    )

    with pytest.raises(NarrationConfirmationRequiredError) as exc_info:
        workflow.generate(_narration_request(article))

    assert exc_info.value.estimate.character_count == len(article.text)
    assert exc_info.value.estimate.listening_minutes == pytest.approx(2.8)
    assert synthesizer.calls == 0


def test_ordinary_narration_does_not_require_confirmation(tmp_path) -> None:
    article = Article(
        url="https://example.com/ordinary",
        title="Ordinary article",
        text="Short article.",
        canonical_url="https://example.com/ordinary",
        content_fingerprint=hashlib.sha256(b"ordinary").hexdigest(),
    )
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=LocalEpisodeStore(tmp_path / "episodes"),
        narration_confirmation_threshold=100,
    )

    assert workflow.generate(_narration_request(article)).audio == b"audio"


def test_reuses_a_matching_narration_episode_without_invoking_external_services(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    retriever = CountingArticleRetriever()
    strategy = CountingNarrationScriptStrategy()
    synthesizer = FakeAudioSynthesizer()
    workflow = EpisodeGenerationWorkflow(
        article_retriever=retriever,
        script_strategies={ScriptStrategy.NARRATION: strategy},
        audio_synthesizer=synthesizer,
        episode_store=store,
    )

    first_episode = workflow.generate(_narration_request())
    second_episode = workflow.generate(_narration_request())

    assert second_episode == first_episode
    assert retriever.calls == 1
    assert strategy.calls == 1
    assert synthesizer.calls == 1


def test_narration_retains_an_updated_content_revision(tmp_path) -> None:
    store = LocalEpisodeStore(tmp_path / "episodes")
    original = Article(
        url="https://example.com/narration",
        title="Narration article",
        text="Original article body.",
        canonical_url="https://example.com/narration",
        content_fingerprint=hashlib.sha256(b"narration-original").hexdigest(),
    )
    revised = Article(
        url=original.url,
        title=original.title,
        text="Revised article body.",
        canonical_url=original.canonical_url,
        content_fingerprint=hashlib.sha256(b"narration-revised").hexdigest(),
    )
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.NARRATION: NarrationScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
        episode_store=store,
    )

    first_episode = workflow.generate(_narration_request(original))
    revised_episode = workflow.generate(_narration_request(revised))

    assert first_episode.revision == 1
    assert revised_episode.revision == 2
    assert revised_episode.article.title.startswith("UPDATED CONTENT")
    assert revised_episode.revision_note == "The source article content changed since revision 1."
