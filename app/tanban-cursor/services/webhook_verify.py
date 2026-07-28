"""Webhook signature helpers matching TanBan's X-TanBan-Signature (sha256=…)."""

from __future__ import annotations

import hashlib
import hmac


def sign_body(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, body: bytes, header_value: str) -> bool:
    expected = sign_body(secret, body)
    return hmac.compare_digest(expected, header_value.strip())
