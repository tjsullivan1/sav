"""Streamlit UI for the blog-to-podcast agent."""

from __future__ import annotations

import logging

import streamlit as st

from blog_to_podcast.config import Settings
from blog_to_podcast.episodes import generate_summary_episode

logger = logging.getLogger(__name__)


def _generate(url: str, settings: Settings, *, refresh_source: bool) -> None:
    """Generate and render a Summary Episode."""
    with st.spinner("Scraping blog and generating podcast..."):
        episode = generate_summary_episode(url.strip(), settings, refresh_source=refresh_source)

    st.success("Podcast ready! 🎧")
    st.subheader(episode.article.title)
    if episode.revision_note:
        st.info(episode.revision_note)
    st.audio(episode.audio, format="audio/mp3")
    st.download_button("Download Podcast", episode.audio, "podcast.mp3", "audio/mp3")
    with st.expander("📄 Podcast Summary"):
        st.write(episode.script)


def main() -> None:
    """Entry point for the Streamlit app."""
    st.set_page_config(page_title="📰 ➡️ 🎙️ Blog to Podcast", page_icon="🎙️")
    st.title("📰 ➡️ 🎙️ Blog to Podcast Agent")

    settings = Settings.from_env()
    url = st.text_input("Enter Blog URL:", "")
    refresh_source = st.checkbox("Check for updated article content")

    if st.button("🎙️ Generate Podcast", disabled=not settings.is_complete):
        if not url.strip():
            st.warning("Please enter a blog URL")
            return
        try:
            _generate(url, settings, refresh_source=refresh_source)
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            logger.exception("podcast generation failed")
            st.error(f"Error: {exc}")

    if not settings.is_complete:
        st.info(settings.startup_feedback())


main()
