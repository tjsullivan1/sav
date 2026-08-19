"""Microsoft Entra bearer-token validation for the Episode API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import jwt

from blog_to_podcast.jobs import AccessDeniedError, Identity


class EntraIdentityResolver:
    """Resolve verified Entra access tokens into public API identities."""

    def __init__(
        self,
        *,
        tenant_id: str,
        audience: str,
        signing_key: Callable[[str], Any],
    ) -> None:
        """Initialize validation with the API tenant, audience, and JWK lookup."""
        self._issuer = f"https://login.microsoftonline.com/{tenant_id}/v2.0"
        self._audience = audience
        self._signing_key = signing_key

    def resolve(self, authorization: str | None) -> Identity:
        """Validate a bearer token and return its user or application identity."""
        if authorization is None or not authorization.startswith("Bearer "):
            raise AccessDeniedError("A valid Entra bearer token is required.")
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise AccessDeniedError("A valid Entra bearer token is required.")
        try:
            claims = jwt.decode(
                token,
                self._signing_key(token),
                algorithms=["RS256"],
                audience=self._audience,
                issuer=self._issuer,
            )
        except jwt.PyJWTError as exc:
            raise AccessDeniedError("A valid Entra bearer token is required.") from exc
        subject = claims.get("oid")
        if not isinstance(subject, str) or not subject:
            raise AccessDeniedError("The Entra token does not identify a caller.")
        roles_value = claims.get("roles", [])
        roles = (
            {role for role in roles_value if isinstance(role, str)}
            if isinstance(roles_value, list)
            else set()
        )
        if claims.get("idtyp") == "app":
            return Identity.application(subject, roles)
        return Identity.user(subject, roles)
