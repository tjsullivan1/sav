import hashlib

import pytest

from blog_to_podcast.episodes import (
    Article,
    ArticleRetrievalError,
    EpisodeGenerationError,
    EpisodeGenerationWorkflow,
    EpisodeRequest,
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
    def synthesize(self, script: str, voice: Voice) -> bytes:
        return b"audio"


def test_generates_a_playable_summary_episode_from_an_episode_request() -> None:
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FakeArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
    )

    episode = workflow.generate(
        EpisodeRequest(
            article=Article(url="https://example.com/useful-article"),
            script_strategy=ScriptStrategy.SUMMARY,
            voice=Voice(id="host-voice"),
        )
    )

    assert episode.audio == b"audio"
    assert episode.article.title == "A useful article"
    assert episode.script == "Here is the summary of A useful article."
    assert episode.article.content_fingerprint == hashlib.sha256(b"Article body.").hexdigest()


def test_reports_an_actionable_retrieval_failure() -> None:
    workflow = EpisodeGenerationWorkflow(
        article_retriever=FailingArticleRetriever(),
        script_strategies={ScriptStrategy.SUMMARY: FakeSummaryScriptStrategy()},
        audio_synthesizer=FakeAudioSynthesizer(),
    )

    with pytest.raises(EpisodeGenerationError, match="retrieve the article"):
        workflow.generate(
            EpisodeRequest(
                article=Article(url="https://example.com/unavailable"),
                script_strategy=ScriptStrategy.SUMMARY,
                voice=Voice(id="host-voice"),
            )
        )
