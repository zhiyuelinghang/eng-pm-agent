# -*- coding: utf-8 -*-
"""Authentication primitives for the embedded AgentScope management app.

The management login identity is deliberately separated from AgentScope's
storage namespace:

* management accounts only authorize access to the administration WebUI;
* the engineering platform uses a dedicated service token;
* every authenticated principal is mapped to one global configuration scope.

This keeps credentials, agents, knowledge bases and other AgentScope settings
platform-global without treating engineering-platform users as AgentScope
users.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Literal


def _base64url_encode(value: bytes) -> str:
    """Encode bytes without padding for compact bearer tokens."""
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    """Decode an unpadded base64url value."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


@dataclass(frozen=True, slots=True)
class AgentScopeAuthConfig:
    """Authentication configuration supplied by the embedding application."""

    admin_username: str
    admin_password: str
    signing_secret: str
    service_token: str
    global_config_id: str = "default"
    management_token_ttl_seconds: int = 8 * 60 * 60

    def __post_init__(self) -> None:
        """Reject ambiguous or unsafe empty authentication configuration."""
        required = {
            "admin_username": self.admin_username,
            "admin_password": self.admin_password,
            "signing_secret": self.signing_secret,
            "service_token": self.service_token,
            "global_config_id": self.global_config_id,
        }
        missing = [name for name, value in required.items() if not value.strip()]
        if missing:
            raise ValueError(
                "AgentScope auth values cannot be empty: " + ", ".join(sorted(missing)),
            )
        if self.management_token_ttl_seconds <= 0:
            raise ValueError("management_token_ttl_seconds must be positive.")
        if secrets.compare_digest(self.signing_secret, self.service_token):
            raise ValueError(
                "AgentScope signing_secret and service_token must differ.",
            )


@dataclass(frozen=True, slots=True)
class AgentScopePrincipal:
    """Authenticated caller identity, independent from stored resources."""

    kind: Literal["management", "service", "legacy"]
    subject: str


@dataclass(frozen=True, slots=True)
class ManagementToken:
    """Issued management bearer token plus its lifetime."""

    access_token: str
    expires_in: int


def verify_management_credentials(
    config: AgentScopeAuthConfig,
    username: str,
    password: str,
) -> bool:
    """Constant-time comparison against the configured management account."""
    username_ok = secrets.compare_digest(
        username.encode("utf-8"),
        config.admin_username.encode("utf-8"),
    )
    password_ok = secrets.compare_digest(
        password.encode("utf-8"),
        config.admin_password.encode("utf-8"),
    )
    return username_ok and password_ok


def issue_management_token(
    config: AgentScopeAuthConfig,
    *,
    now: int | None = None,
) -> ManagementToken:
    """Issue a signed, expiring token for the management WebUI."""
    issued_at = int(time.time() if now is None else now)
    payload = {
        "kind": "management",
        "sub": config.admin_username,
        "iat": issued_at,
        "exp": issued_at + config.management_token_ttl_seconds,
        "nonce": secrets.token_hex(8),
    }
    encoded_payload = _base64url_encode(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
    )
    signature = hmac.new(
        config.signing_secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    return ManagementToken(
        access_token=f"{encoded_payload}.{_base64url_encode(signature)}",
        expires_in=config.management_token_ttl_seconds,
    )


def authenticate_bearer_token(
    config: AgentScopeAuthConfig,
    token: str,
    *,
    now: int | None = None,
) -> AgentScopePrincipal | None:
    """Authenticate either the platform service token or management token."""
    if secrets.compare_digest(
        token.encode("utf-8"),
        config.service_token.encode("utf-8"),
    ):
        return AgentScopePrincipal(kind="service", subject="engineering-platform")

    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        supplied_signature = _base64url_decode(encoded_signature)
        expected_signature = hmac.new(
            config.signing_secret.encode("utf-8"),
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(supplied_signature, expected_signature):
            return None
        payload = json.loads(_base64url_decode(encoded_payload))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None

    current_time = int(time.time() if now is None else now)
    if (
        payload.get("kind") != "management"
        or payload.get("sub") != config.admin_username
        or not isinstance(payload.get("exp"), int)
        or payload["exp"] <= current_time
    ):
        return None
    return AgentScopePrincipal(
        kind="management",
        subject=config.admin_username,
    )
