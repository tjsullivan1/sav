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
from blog_to_podcast.ui import GenerationJobApi, GenerationJobApiError, GenerationJobView

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


def build_generation_job_api(settings: Settings) -> GenerationJobApi:
    """Build the cloud UI's managed-identity API adapter."""
    return GenerationJobApi(
        base_url=settings.generation_api_url,
        scope=settings.generation_api_scope,
    )


def _render_cloud_job(api: GenerationJobApi) -> None:
    """Render the current durable Generation Job and its available actions."""
    job = st.session_state.get("generation_job")
    if not isinstance(job, GenerationJobView):
        return

    st.subheader("Generation Job")
    st.info(f"{job.status.replace('_', ' ').title()}: {job.message}")
    if job.status == "awaiting_confirmation" and job.estimate is not None:
        st.warning(
            f"Narration contains {job.estimate.character_count:,} characters and is estimated to "
            f"take {job.estimate.listening_minutes:.1f} minutes to listen to."
        )
    if st.button("Refresh Job Status"):
        try:
            st.session_state["generation_job"] = api.get(job.id)
            st.rerun()
        except GenerationJobApiError as exc:
            st.error(str(exc))

    if job.status == "awaiting_confirmation" and st.button("Confirm synthesis"):
        try:
            st.session_state["generation_job"] = api.confirm(job.id)
            st.rerun()
        except GenerationJobApiError as exc:
            st.error(str(exc))

    if job.status in {"queued", "retrieving", "awaiting_confirmation"} and st.button("Cancel Job"):
        try:
            st.session_state["generation_job"] = api.cancel(job.id)
            st.rerun()
        except GenerationJobApiError as exc:
            st.error(str(exc))

    if job.status == "completed":
        try:
            audio = api.episode(job.id)
        except GenerationJobApiError as exc:
            st.error(str(exc))
        else:
            st.success("Episode ready!")
            st.audio(audio, format="audio/mp3")
            st.download_button("Download Episode", audio, "episode.mp3", "audio/mp3")


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

    if settings.is_cloud_ui_configured:
        api = build_generation_job_api(settings)
        if st.button("🎙️ Generate Episode"):
            if not url.strip():
                st.warning("Please enter an Article URL")
                return
            if not voice_id.strip():
                st.warning("Please enter a Voice ID")
                return
            try:
                st.session_state["generation_job"] = api.submit(
                    article_url=url.strip(),
                    script_strategy=strategy.value,
                    voice_id=voice_id.strip(),
                    refresh_source=refresh_source,
                )
                st.rerun()
            except GenerationJobApiError as exc:
                st.error(str(exc))
        _render_cloud_job(api)
        return

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
