import pytest

from blog_to_podcast.config import Settings
from blog_to_podcast.summarizer import SummarizationError, summarize_blog


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeAgent:
    def __init__(self, response: object) -> None:
        self.response = response
        self.prompts: list[str] = []

    def run(self, prompt: str) -> object:
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def settings() -> Settings:
    return Settings(
        azure_openai_base_url="https://example.openai.azure.com/openai/v1/",
        azure_openai_deployment="gpt-4o",
        azure_openai_api_key="aoai-key",
        elevenlabs_api_key="el-key",
        firecrawl_api_key="fc-key",
    )


def test_summarize_blog_returns_stripped_content(settings: Settings) -> None:
    agent = FakeAgent(FakeResponse("  A punchy summary.  "))

    summary = summarize_blog("https://blog.example/post", settings, agent=agent)

    assert summary == "A punchy summary."
    assert "https://blog.example/post" in agent.prompts[0]


def test_summarize_blog_raises_on_empty_content(settings: Settings) -> None:
    agent = FakeAgent(FakeResponse("   "))

    with pytest.raises(SummarizationError):
        summarize_blog("https://blog.example/post", settings, agent=agent)
