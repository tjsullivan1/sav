import hashlib

import pytest

from blog_to_podcast.episodes import (
    Article,
    ArticleRetrievalError,
    EpisodeGenerationError,
    EpisodeGenerationWorkflow,
    EpisodeRequest,
    LocalEpisodeStore,
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


def _request(article: Article | None = None) -> EpisodeRequest:
    return EpisodeRequest(
        article=article or Article(url="https://example.com/useful-article"),
        script_strategy=ScriptStrategy.SUMMARY,
        voice=Voice(id="host-voice"),
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
    assert revised_episode.article.title.startswith("UPDATED CONTENT")
    assert "Revision 2" in revised_episode.article.title
    assert revised_episode.revision_note == "The source article content changed since revision 1."
    assert store.find(_request(original), original.content_fingerprint) == first_episode


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
