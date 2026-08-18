"""Streamlit UI for the blog-to-podcast agent."""

from __future__ import annotations

import logging

import streamlit as st

from blog_to_podcast.config import Settings
from blog_to_podcast.episodes import (
    NarrationConfirmationRequiredError,
    ScriptStrategy,
    generate_episode,
)

logger = logging.getLogger(__name__)


def _generate(
    url: str,
    settings: Settings,
    script_strategy: ScriptStrategy,
    *,
    voice_id: str,
    refresh_source: bool,
    narration_confirmed: bool,
) -> None:
    """Generate and render an Episode."""
    with st.spinner("Scraping blog and generating podcast..."):
        episode = generate_episode(
            url.strip(),
            settings,
            script_strategy,
            voice_id=voice_id,
            refresh_source=refresh_source,
            narration_confirmed=narration_confirmed,
        )

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
    strategy = ScriptStrategy(
        st.selectbox(
            "Script strategy",
            options=[strategy.value for strategy in ScriptStrategy],
            format_func=str.title,
        )
    )
    voice_id = st.text_input(
        "Voice ID",
        value=settings.voice_id,
        help="Enter the ElevenLabs voice identifier for this Episode.",
    )
    refresh_source = st.checkbox("Check for updated article content")
    narration_key = f"{url.strip()}:{strategy.value}"
    narration_preflight_ready = (
        st.session_state.get("narration_preflight_key") == narration_key
        and strategy is ScriptStrategy.NARRATION
    )
    narration_confirmed = False
    if narration_preflight_ready:
        st.warning(str(st.session_state["narration_preflight_estimate"]))
        narration_confirmed = st.checkbox(
            "I confirm this Narration run after reviewing its estimated size and duration."
        )

    if st.button("🎙️ Generate Podcast", disabled=not settings.is_complete):
        if not url.strip():
            st.warning("Please enter a blog URL")
            return
        if not voice_id.strip():
            st.warning("Please enter a Voice ID")
            return
        try:
            _generate(
                url,
                settings,
                strategy,
                voice_id=voice_id.strip(),
                refresh_source=refresh_source,
                narration_confirmed=narration_confirmed,
            )
        except NarrationConfirmationRequiredError as exc:
            st.session_state["narration_preflight_key"] = narration_key
            st.session_state["narration_preflight_estimate"] = str(exc)
            st.rerun()
        except Exception as exc:  # noqa: BLE001 - surface any failure to the user
            logger.exception("podcast generation failed")
            st.error(f"Error: {exc}")
        else:
            st.session_state.pop("narration_preflight_key", None)
            st.session_state.pop("narration_preflight_estimate", None)

    if not settings.is_complete:
        st.info(settings.startup_feedback())


main()
