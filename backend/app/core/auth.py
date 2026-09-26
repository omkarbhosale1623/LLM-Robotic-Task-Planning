"""Supabase JWT authentication — standard-library HS256 verification.

This module verifies Supabase's **HS256** JWTs using only the Python standard
library (``hmac`` / ``hashlib`` / ``base64`` / ``json``), so the backend needs no
extra dependency (``pyjwt`` may be absent in the offline environment). The token
is the one Supabase Auth issues to a signed-in user; its signature is the
project's ``SUPABASE_JWT_SECRET``.

Auth is **always enforced** for every ``/api/v1/**`` REST route and every
``/ws/**`` WebSocket. The public surface (``/health``, ``/metrics``, ``/``,
``/docs``, ``/openapi.json``, ``/redoc``) is left open.

For projects configured with **asymmetric** Supabase keys (RS256 / ES256 via a
JWKS endpoint), swap the verification body for a JWKS fetch + asymmetric verify;
the clearly-marked extension point is :func:`_verify_signature`.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Header, status

from app.core.logging import get_logger

logger = get_logger(__name__)


class AuthError(Exception):
    """Raised when a token is missing, malformed, expired, or has a bad signature.

    Maps to HTTP 401 via the exception handler registered in
    :mod:`app.core.errors`.
    """

    status_code: int = status.HTTP_401_UNAUTHORIZED
    error_type: str = "authentication_error"

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class User:
    """The authenticated principal extracted from a verified Supabase JWT."""

    id: str  # Supabase auth uid (the JWT `sub` claim).
    email: str | None = None
    role: str = "authenticated"

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "email": self.email, "role": self.role}


# ---------------------------------------------------------------------------
# base64url helpers
# ---------------------------------------------------------------------------


def _b64url_decode(segment: str) -> bytes:
    """Decode a base64url segment, restoring stripped ``=`` padding."""

    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except (binascii.Error, ValueError) as exc:
        raise AuthError("malformed token segment") from exc


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------


def _verify_signature(header_b64: str, payload_b64: str, signature: bytes, secret: str) -> bool:
    """Recompute the HS256 MAC and constant-time compare it.

    Extension point: to support asymmetric Supabase keys (RS256/ES256), replace
    this body with a JWKS lookup keyed by the token header's ``kid`` and an
    asymmetric ``verify`` using the project's public keys.
    """

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return hmac.compare_digest(expected, signature)


def verify_supabase_jwt(token: str, settings: Any) -> User:
    """Verify a Supabase HS256 JWT and return the authenticated :class:`User`.

    Validates structure, signature (HMAC-SHA256 over ``header.payload`` with the
    project ``SUPABASE_JWT_SECRET``), expiry (``exp``), and — when present —
    ``aud`` / ``iss``. Raises :class:`AuthError` (401) on any failure.
    """

    secret = settings.supabase_jwt_secret
    if not secret:
        # No secret configured: refuse rather than silently allowing access.
        raise AuthError("server is not configured with SUPABASE_JWT_SECRET")

    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("token is not a well-formed JWT")
    header_b64, payload_b64, signature_b64 = parts

    # Header must declare HS256 (this verifier only supports symmetric signing).
    try:
        header = json.loads(_b64url_decode(header_b64))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthError("invalid token header") from exc
    alg = str(header.get("alg", "")).upper()
    if alg != "HS256":
        raise AuthError(
            f"unsupported JWT alg '{alg}'; this server verifies HS256 Supabase tokens"
        )

    signature = _b64url_decode(signature_b64)
    if not _verify_signature(header_b64, payload_b64, signature, secret):
        raise AuthError("invalid token signature")

    try:
        claims = json.loads(_b64url_decode(payload_b64))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AuthError("invalid token payload") from exc
    if not isinstance(claims, dict):
        raise AuthError("token payload is not a JSON object")

    # Expiry (with a small clock-skew leeway).
    exp = claims.get("exp")
    if exp is not None:
        try:
            if float(exp) < time.time() - 5:
                raise AuthError("token has expired")
        except (TypeError, ValueError) as exc:
            raise AuthError("token has an invalid 'exp' claim") from exc

    # Not-before, if present.
    nbf = claims.get("nbf")
    if nbf is not None:
        try:
            if float(nbf) > time.time() + 5:
                raise AuthError("token is not yet valid")
        except (TypeError, ValueError) as exc:
            raise AuthError("token has an invalid 'nbf' claim") from exc

    # Audience / issuer — verified only when configured and present on the token.
    expected_aud = getattr(settings, "supabase_jwt_aud", None)
    if expected_aud and "aud" in claims:
        aud = claims["aud"]
        aud_values = aud if isinstance(aud, list) else [aud]
        if expected_aud not in aud_values:
            raise AuthError("token audience mismatch")

    expected_iss = getattr(settings, "supabase_jwt_iss", None)
    if expected_iss and "iss" in claims and claims["iss"] != expected_iss:
        raise AuthError("token issuer mismatch")

    sub = claims.get("sub")
    if not sub:
        raise AuthError("token is missing the 'sub' (user id) claim")

    return User(
        id=str(sub),
        email=claims.get("email"),
        role=str(claims.get("role", "authenticated")),
    )


# ---------------------------------------------------------------------------
# FastAPI / WebSocket integration
# ---------------------------------------------------------------------------


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise AuthError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header must be 'Bearer <token>'")
    return token.strip()


def require_user(authorization: str | None = Header(default=None)):
    """FastAPI dependency: verify the Bearer token and return the :class:`User`.

    Imported and wired with the live settings in :mod:`app.api.deps` (the router
    dependency closes over the app's settings). Raises :class:`AuthError` (401)
    when the header is missing or the token is invalid.
    """

    # This module-level form is kept for documentation/testing; the live
    # dependency is built in app.api.deps.make_require_user(settings) so it can
    # bind the per-app Settings. See that factory for the enforced version.
    raise NotImplementedError(
        "use app.api.deps.make_require_user(settings) to build the live dependency"
    )


async def authenticate_ws(websocket: Any, settings: Any) -> User | None:
    """Authenticate a WebSocket connection, returning the :class:`User` or None.

    Reads the token from the ``token`` query parameter (preferred for browsers),
    falling back to the ``Authorization`` header and then the
    ``sec-websocket-protocol`` header. On any failure the socket is closed with
    code ``1008`` (policy violation) and ``None`` is returned so the caller can
    abort cleanly.
    """

    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header:
            try:
                token = _extract_bearer(auth_header)
            except AuthError:
                token = None
    if not token:
        # Some clients pass the token via the WS subprotocol header.
        proto = websocket.headers.get("sec-websocket-protocol")
        if proto:
            token = proto.split(",")[0].strip()

    if not token:
        await websocket.close(code=1008)
        return None

    try:
        return verify_supabase_jwt(token, settings)
    except AuthError as exc:
        logger.info("WebSocket auth rejected: %s", exc.message)
        await websocket.close(code=1008)
        return None
