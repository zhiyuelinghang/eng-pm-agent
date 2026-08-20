"""连接凭据的服务端对称加密。"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


_CIPHERTEXT_PREFIX = "v1:"


def _fernet() -> Fernet:
    settings = get_settings()
    source = settings.connector_secret_key.strip() or settings.jwt_secret.strip()
    if not source:
        raise RuntimeError("CONNECTOR_SECRET_KEY 或 JWT_SECRET 至少需要配置一项")
    digest = hashlib.sha256(source.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_connector_secret(value: str) -> str:
    """Encrypt one non-empty credential with a versioned envelope."""

    normalized = value.strip()
    if not normalized:
        raise ValueError("连接凭据不能为空")
    encrypted = _fernet().encrypt(normalized.encode("utf-8")).decode("ascii")
    return f"{_CIPHERTEXT_PREFIX}{encrypted}"


def decrypt_connector_secret(value: str | None) -> str | None:
    """Decrypt a stored credential for a connector runtime integration."""

    if not value:
        return None
    if not value.startswith(_CIPHERTEXT_PREFIX):
        raise ValueError("连接凭据密文版本不受支持")
    try:
        plain = _fernet().decrypt(
            value.removeprefix(_CIPHERTEXT_PREFIX).encode("ascii"),
        )
    except (InvalidToken, ValueError) as exc:
        raise ValueError("连接凭据无法解密，请重新保存配置") from exc
    return plain.decode("utf-8")
