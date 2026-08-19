"""FastAPI adapter for the authenticated Generation Job request-reply workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, Header, HTTPException, Response, status
from pydantic import BaseModel, HttpUrl

from blog_to_podcast.episodes import Article, EpisodeRequest, ScriptStrategy, Voice
from blog_to_podcast.jobs import (
    AccessDeniedError,
    GenerationJob,
    GenerationJobNotFoundError,
    GenerationJobService,
    Identity,
    InvalidJobTransitionError,
)


class IdentityResolver(Protocol):
    """Resolves a verified Entra bearer token to a caller Identity."""

    def resolve(self, authorization: str | None) -> Identity:
        """Return the caller Identity from an HTTP Authorization header."""


class EpisodeRequestBody(BaseModel):
    """Request body accepted by the Generation Job API."""

    article_url: HttpUrl
    script_strategy: ScriptStrategy
    voice_id: str
    refresh_source: bool = False

    def to_domain(self) -> EpisodeRequest:
        """Translate the API request into the UI-independent domain request."""
        return EpisodeRequest(
            article=Article(url=str(self.article_url)),
            script_strategy=self.script_strategy,
            voice=Voice(id=self.voice_id),
            refresh_source=self.refresh_source,
        )


class GenerationJobBody(BaseModel):
    """Listener-readable Generation Job representation."""

    id: str
    status: str
    message: str
    status_url: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, job: GenerationJob) -> GenerationJobBody:
        """Translate a domain Generation Job into the stable API response."""
        return cls(
            id=job.id,
            status=job.status.value,
            message=job.message,
            status_url=f"/v1/generation-jobs/{job.id}",
            created_at=job.created_at,
            updated_at=job.updated_at,
        )


def create_app(service: GenerationJobService, identity_resolver: IdentityResolver) -> FastAPI:
    """Create the authenticated FastAPI entry point for Generation Jobs."""
    app = FastAPI(title="Blog to Podcast Episode API")

    def identity(authorization: Annotated[str | None, Header()] = None) -> Identity:
        try:
            return identity_resolver.resolve(authorization)
        except AccessDeniedError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    def operation_error(exc: Exception) -> HTTPException:
        if isinstance(exc, AccessDeniedError):
            return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
        if isinstance(exc, GenerationJobNotFoundError):
            return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        if isinstance(exc, InvalidJobTransitionError):
            return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        raise exc

    @app.post(
        "/v1/generation-jobs",
        response_model=GenerationJobBody,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def submit_generation_job(
        request: EpisodeRequestBody, caller: Identity = Depends(identity)
    ) -> GenerationJobBody:
        """Submit an Episode Request without holding a browser connection."""
        try:
            return GenerationJobBody.from_domain(service.submit(request.to_domain(), caller))
        except (AccessDeniedError, GenerationJobNotFoundError, InvalidJobTransitionError) as exc:
            raise operation_error(exc) from exc

    @app.get("/v1/generation-jobs/{job_id}", response_model=GenerationJobBody)
    def get_generation_job(job_id: str, caller: Identity = Depends(identity)) -> GenerationJobBody:
        """Poll one Generation Job's listener-readable status."""
        try:
            return GenerationJobBody.from_domain(service.get(job_id, caller))
        except (AccessDeniedError, GenerationJobNotFoundError, InvalidJobTransitionError) as exc:
            raise operation_error(exc) from exc

    @app.post("/v1/generation-jobs/{job_id}/confirm", response_model=GenerationJobBody)
    def confirm_generation_job(
        job_id: str, caller: Identity = Depends(identity)
    ) -> GenerationJobBody:
        """Confirm a Job that is waiting before expensive synthesis."""
        try:
            return GenerationJobBody.from_domain(service.confirm(job_id, caller))
        except (AccessDeniedError, GenerationJobNotFoundError, InvalidJobTransitionError) as exc:
            raise operation_error(exc) from exc

    @app.post("/v1/generation-jobs/{job_id}/cancel", response_model=GenerationJobBody)
    def cancel_generation_job(
        job_id: str, caller: Identity = Depends(identity)
    ) -> GenerationJobBody:
        """Cancel a Job before synthesis begins."""
        try:
            return GenerationJobBody.from_domain(service.cancel(job_id, caller))
        except (AccessDeniedError, GenerationJobNotFoundError, InvalidJobTransitionError) as exc:
            raise operation_error(exc) from exc

    @app.get("/v1/generation-jobs/{job_id}/episode")
    def get_completed_episode(job_id: str, caller: Identity = Depends(identity)) -> Response:
        """Retrieve the completed Episode's playable audio."""
        try:
            episode = service.episode(job_id, caller)
        except (AccessDeniedError, GenerationJobNotFoundError, InvalidJobTransitionError) as exc:
            raise operation_error(exc) from exc
        return Response(content=episode.audio, media_type="audio/mpeg")

    return app
