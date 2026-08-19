"""Authenticated API adapter used by the cloud Streamlit UI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from azure.identity import DefaultAzureCredential


class TokenProvider(Protocol):
    """Obtains an access token for the Generation Job API."""

    def get_token(self, scope: str) -> str:
        """Return an access token for the supplied API scope."""


class HttpTransport(Protocol):
    """Sends HTTPS requests to the Generation Job API."""

    def send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> ApiResponse:
        """Return the API response for one request."""


@dataclass(frozen=True)
class ApiResponse:
    """Raw HTTP response returned by an API transport."""

    status_code: int
    body: bytes
    content_type: str = ""


@dataclass(frozen=True)
class GenerationJobView:
    """Listener-visible representation of a Generation Job."""

    id: str
    status: str
    message: str
    status_url: str


class GenerationJobApiError(RuntimeError):
    """Raised when the authenticated Generation Job API rejects a UI request."""


class ManagedIdentityTokenProvider:
    """Gets API tokens from the UI Container App's managed identity."""

    def __init__(self) -> None:
        """Initialize the Azure managed-identity credential chain."""
        self._credential = DefaultAzureCredential()

    def get_token(self, scope: str) -> str:
        """Return a managed-identity access token for the API application."""
        return self._credential.get_token(scope).token


class UrllibTransport:
    """HTTPS transport implemented with Python's standard library."""

    def send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> ApiResponse:
        """Send one request and retain non-success API responses for error handling."""
        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is deployment config.
                return ApiResponse(
                    status_code=response.status,
                    body=response.read(),
                    content_type=response.headers.get_content_type(),
                )
        except HTTPError as exc:
            return ApiResponse(
                status_code=exc.code,
                body=exc.read(),
                content_type=exc.headers.get_content_type(),
            )
        except URLError as exc:
            raise GenerationJobApiError("The Episode API could not be reached.") from exc


class GenerationJobApi:
    """Calls the authenticated Generation Job API on behalf of the Streamlit UI."""

    def __init__(
        self,
        *,
        base_url: str,
        scope: str,
        token_provider: TokenProvider | None = None,
        transport: HttpTransport | None = None,
    ) -> None:
        """Configure the API endpoint and managed-identity authentication boundary."""
        self._base_url = base_url.rstrip("/")
        self._scope = scope
        self._token_provider = token_provider or ManagedIdentityTokenProvider()
        self._transport = transport or UrllibTransport()

    def submit(
        self,
        *,
        article_url: str,
        script_strategy: str,
        voice_id: str,
        refresh_source: bool,
    ) -> GenerationJobView:
        """Submit an Episode Request and return its durable Generation Job."""
        return self._job(
            "POST",
            "/v1/generation-jobs",
            {
                "article_url": article_url,
                "script_strategy": script_strategy,
                "voice_id": voice_id,
                "refresh_source": refresh_source,
            },
        )

    def get(self, job_id: str) -> GenerationJobView:
        """Poll one Generation Job's listener-visible status."""
        return self._job("GET", f"/v1/generation-jobs/{job_id}")

    def confirm(self, job_id: str) -> GenerationJobView:
        """Confirm a Job before synthesis begins."""
        return self._job("POST", f"/v1/generation-jobs/{job_id}/confirm")

    def cancel(self, job_id: str) -> GenerationJobView:
        """Cancel a Job before synthesis begins."""
        return self._job("POST", f"/v1/generation-jobs/{job_id}/cancel")

    def episode(self, job_id: str) -> bytes:
        """Retrieve completed Episode audio through the authenticated API."""
        response = self._send("GET", f"/v1/generation-jobs/{job_id}/episode")
        return response.body

    def _job(
        self, method: str, path: str, body: dict[str, object] | None = None
    ) -> GenerationJobView:
        """Execute a Job endpoint and parse its stable public response."""
        response = self._send(method, path, body)
        try:
            payload = json.loads(response.body)
            return GenerationJobView(
                id=payload["id"],
                status=payload["status"],
                message=payload["message"],
                status_url=payload["status_url"],
            )
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise GenerationJobApiError(
                "The Episode API returned an invalid Job response."
            ) from exc

    def _send(self, method: str, path: str, body: dict[str, object] | None = None) -> ApiResponse:
        """Attach the managed-identity token and raise a listener-safe API error on failure."""
        encoded_body = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {self._token_provider.get_token(self._scope)}",
            "Accept": "application/json",
        }
        if encoded_body is not None:
            headers["Content-Type"] = "application/json"
        response = self._transport.send(method, f"{self._base_url}{path}", headers, encoded_body)
        if 200 <= response.status_code < 300:
            return response
        raise GenerationJobApiError(self._error_message(response))

    @staticmethod
    def _error_message(response: ApiResponse) -> str:
        """Return a listener-readable API error without disclosing implementation internals."""
        try:
            detail = json.loads(response.body).get("detail")
        except (AttributeError, json.JSONDecodeError):
            detail = None
        if isinstance(detail, str) and detail:
            return detail
        return "The Episode API could not complete this request."
