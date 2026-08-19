from __future__ import annotations

import json

from blog_to_podcast.ui import ApiResponse, GenerationJobApi


class FakeTokenProvider:
    def get_token(self, scope: str) -> str:
        assert scope == "api://blog-to-podcast-prod-api/.default"
        return "managed-identity-token"


class FakeTransport:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str], bytes | None]] = []
        self.responses = [
            ApiResponse(
                status_code=202,
                body=json.dumps(
                    {
                        "id": "job-1",
                        "status": "queued",
                        "message": "Episode request queued.",
                        "status_url": "/v1/generation-jobs/job-1",
                    }
                ).encode(),
            ),
            ApiResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "id": "job-1",
                        "status": "awaiting_confirmation",
                        "message": "Confirmation is required before synthesis.",
                        "status_url": "/v1/generation-jobs/job-1",
                        "estimate": {
                            "character_count": 12000,
                            "listening_minutes": 13.3,
                        },
                    }
                ).encode(),
            ),
            ApiResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "id": "job-1",
                        "status": "queued",
                        "message": "Confirmation received; synthesis queued.",
                        "status_url": "/v1/generation-jobs/job-1",
                    }
                ).encode(),
            ),
            ApiResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "id": "job-1",
                        "status": "cancelled",
                        "message": "Episode generation cancelled.",
                        "status_url": "/v1/generation-jobs/job-1",
                    }
                ).encode(),
            ),
            ApiResponse(status_code=200, body=b"mp3-bytes", content_type="audio/mpeg"),
        ]

    def send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None = None
    ) -> ApiResponse:
        self.requests.append((method, url, headers, body))
        return self.responses.pop(0)


def test_ui_submits_polls_cancels_and_retrieves_an_episode_through_the_api() -> None:
    transport = FakeTransport()
    api = GenerationJobApi(
        base_url="https://api.example.test/",
        scope="api://blog-to-podcast-prod-api/.default",
        token_provider=FakeTokenProvider(),
        transport=transport,
    )

    submitted = api.submit(
        article_url="https://example.com/article",
        script_strategy="summary",
        voice_id="voice",
        refresh_source=True,
    )
    polled = api.get(submitted.id)
    confirmed = api.confirm(submitted.id)
    cancelled = api.cancel(submitted.id)
    audio = api.episode(submitted.id)

    assert submitted.status == "queued"
    assert polled.message == "Confirmation is required before synthesis."
    assert polled.estimate == {"character_count": 12000, "listening_minutes": 13.3}
    assert confirmed.status == "queued"
    assert cancelled.status == "cancelled"
    assert audio == b"mp3-bytes"
    assert [(method, url) for method, url, _, _ in transport.requests] == [
        ("POST", "https://api.example.test/v1/generation-jobs"),
        ("GET", "https://api.example.test/v1/generation-jobs/job-1"),
        ("POST", "https://api.example.test/v1/generation-jobs/job-1/confirm"),
        ("POST", "https://api.example.test/v1/generation-jobs/job-1/cancel"),
        ("GET", "https://api.example.test/v1/generation-jobs/job-1/episode"),
    ]
    assert all(
        headers["Authorization"] == "Bearer managed-identity-token"
        for _, _, headers, _ in transport.requests
    )
    assert json.loads(transport.requests[0][3] or b"{}") == {
        "article_url": "https://example.com/article",
        "script_strategy": "summary",
        "voice_id": "voice",
        "refresh_source": True,
    }
