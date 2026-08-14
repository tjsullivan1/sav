"""Blog scraping and summarization backed by an agno agent."""

from __future__ import annotations

import logging

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.tools.firecrawl import FirecrawlTools

from blog_to_podcast.config import MAX_SUMMARY_CHARS, Settings

logger = logging.getLogger(__name__)

INSTRUCTIONS = [
    (
        f"Scrape the blog URL and create a concise, engaging summary "
        f"(max {MAX_SUMMARY_CHARS} characters) suitable for a podcast."
    ),
    "The summary should be conversational and capture the main points.",
]


class SummarizationError(RuntimeError):
    """Raised when the agent fails to produce a usable summary."""


def build_agent(settings: Settings) -> Agent:
    """Create the blog summarizer agent wired to Azure OpenAI and Firecrawl.

    Args:
        settings: Resolved credentials and model configuration.

    Returns:
        A configured agno ``Agent`` ready to scrape and summarize a blog post.

    """
    return Agent(
        name="Blog Summarizer",
        model=OpenAIChat(
            id=settings.azure_openai_deployment.strip(),
            api_key=settings.azure_openai_api_key,
            base_url=settings.azure_openai_base_url.strip(),
        ),
        tools=[FirecrawlTools(api_key=settings.firecrawl_api_key)],
        instructions=INSTRUCTIONS,
    )


def summarize_blog(url: str, settings: Settings, agent: Agent | None = None) -> str:
    """Scrape a blog post and return a podcast-ready summary.

    Args:
        url: Public URL of the blog post to convert.
        settings: Resolved credentials and model configuration.
        agent: Optional pre-built agent, primarily for testing.

    Returns:
        The summary text.

    Raises:
        SummarizationError: If the agent returns an empty response.

    """
    agent = agent or build_agent(settings)
    logger.info("summarizing blog", extra={"url": url})

    response: RunOutput = agent.run(f"Scrape and summarize this blog for a podcast: {url}")
    summary = getattr(response, "content", None) or str(response or "")
    summary = summary.strip()

    if not summary:
        raise SummarizationError("The summarizer returned an empty response.")
    return summary
