"""Streamlit UI for the blog-to-podcast agent."""

from __future__ import annotations

import logging

import streamlit as st

from blog_to_podcast.config import Settings
from blog_to_podcast.summarizer import summarize_blog
from blog_to_podcast.tts import text_to_speech

logger = logging.getLogger(__name__)


def _sidebar_settings() -> Settings:
    """Render the credential sidebar, pre-filled from the environment."""
    defaults = Settings.from_env()
    st.sidebar.header("🔑 API Configuration")

    return Settings(
        azure_openai_base_url=st.sidebar.text_input(
            "Azure OpenAI v1 Base URL",
            value=defaults.azure_openai_base_url,
            placeholder="https://<resource-name>.openai.azure.com/openai/v1/",
        ),
        azure_openai_deployment=st.sidebar.text_input(
            "Azure OpenAI Deployment Name",
            value=defaults.azure_openai_deployment,
            placeholder="gpt-4o",
        ),
        azure_openai_api_key=st.sidebar.text_input(
            "Azure OpenAI API Key", value=defaults.azure_openai_api_key, type="password"
        ),
        elevenlabs_api_key=st.sidebar.text_input(
            "ElevenLabs API Key", value=defaults.elevenlabs_api_key, type="password"
        ),
        firecrawl_api_key=st.sidebar.text_input(
            "Firecrawl API Key", value=defaults.firecrawl_api_key, type="password"
        ),
        voice_id=defaults.voice_id,
        tts_model_id=defaults.tts_model_id,
    )


def _generate(url: str, settings: Settings) -> None:
    """Run the scrape → summarize → narrate pipeline and render the results."""
    with st.spinner("Scraping blog and generating podcast..."):
        summary = summarize_blog(url.strip(), settings)
        audio_bytes = text_to_speech(summary, settings)

    st.success("Podcast generated! 🎧")
    st.audio(audio_bytes, format="audio/mp3")
    st.download_button("Download Podcast", audio_bytes, "podcast.mp3", "audio/mp3")
    with st.expander("📄 Podcast Summary"):
        st.write(summary)


def main() -> None:
    """Entry point for the Streamlit app."""
    st.set_page_config(page_title="📰 ➡️ 🎙️ Blog to Podcast", page_icon="🎙️")
    st.title("📰 ➡️ 🎙️ Blog to Podcast Agent")

    settings = _sidebar_settings()
    url = st.text_input("Enter Blog URL:", "")

    if st.button("🎙️ Generate Podcast", disabled=not settings.is_complete):
        if not url.strip():
            st.warning("Please enter a blog URL")
            return
        try:
            _generate(url, settings)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            logger.exception("podcast generation failed")
            st.error(f"Error: {exc}")

    if not settings.is_complete:
        st.info(
            "Add the missing credentials in the sidebar: " + ", ".join(settings.missing_fields())
        )


main()
