"""Local cookie-based auth service using signed JWT cookies."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Response

from src.models.repositories.auth_user_repository import AuthUserRepository

AUTH_COOKIE_NAME = "blogify_access_token"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _json_dumps(value: dict[str, Any]) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


@dataclass(slots=True)
class LocalAuthUser:
    user_id: int
    email: str
    display_name: str | None


class LocalAuthService:
    def __init__(self) -> None:
        self.secret = os.getenv("JWT_SECRET_KEY") or os.getenv("LOCAL_AUTH_SECRET") or "dev-blogify-local-auth-secret"
        self.issuer = os.getenv("JWT_ISSUER", "blogify-local-auth")
        self.audience = os.getenv("JWT_AUDIENCE", "blogify-api")
        self.ttl_seconds = int(os.getenv("LOCAL_AUTH_TTL_SECONDS", "28800"))
        self.cookie_secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
        self.cookie_samesite = os.getenv("COOKIE_SAMESITE", "lax").capitalize()

    def hash_password(self, password: str) -> str:
        salt = secrets.token_bytes(16)
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
        return f"scrypt${_b64url_encode(salt)}${_b64url_encode(digest)}"

    def verify_password(self, password: str, password_hash: str) -> bool:
        try:
            scheme, encoded_salt, encoded_digest = password_hash.split("$", 2)
        except ValueError:
            return False
        if scheme != "scrypt":
            return False
        salt = _b64url_decode(encoded_salt)
        expected = _b64url_decode(encoded_digest)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=64)
        return hmac.compare_digest(actual, expected)

    def issue_token(self, user: LocalAuthUser) -> str:
        now = datetime.now(timezone.utc)
        payload = {
            "sub": str(user.user_id),
            "email": user.email,
            "display_name": user.display_name,
            "iss": self.issuer,
            "aud": self.audience,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=self.ttl_seconds)).timestamp()),
        }
        header = {"alg": "HS256", "typ": "JWT"}
        encoded_header = _b64url_encode(_json_dumps(header))
        encoded_payload = _b64url_encode(_json_dumps(payload))
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        signature = hmac.new(self.secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        return f"{encoded_header}.{encoded_payload}.{_b64url_encode(signature)}"

    def decode_token(self, token: str) -> dict[str, Any]:
        encoded_header, encoded_payload, encoded_signature = token.split(".", 2)
        signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
        expected_signature = hmac.new(
            self.secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        if not hmac.compare_digest(expected_signature, _b64url_decode(encoded_signature)):
            raise ValueError("Invalid token signature")
        payload = json.loads(_b64url_decode(encoded_payload))
        now_ts = int(datetime.now(timezone.utc).timestamp())
        if payload.get("aud") != self.audience:
            raise ValueError("Invalid token audience")
        if payload.get("iss") != self.issuer:
            raise ValueError("Invalid token issuer")
        if int(payload.get("exp", 0)) < now_ts:
            raise ValueError("Token expired")
        return payload

    def set_auth_cookie(self, response: Response, token: str) -> None:
        response.set_cookie(
            key=AUTH_COOKIE_NAME,
            value=token,
            httponly=True,
            samesite=self.cookie_samesite,
            secure=self.cookie_secure,
            max_age=self.ttl_seconds,
            path="/",
        )

    def clear_auth_cookie(self, response: Response) -> None:
        response.delete_cookie(key=AUTH_COOKIE_NAME, path="/")

    async def ensure_seed_user(self, auth_repo: AuthUserRepository) -> None:
        if await auth_repo.count_all() > 0:
            return
        seed_email = os.getenv("LOCAL_AUTH_SEED_EMAIL", "dev@blogify.local")
        seed_password = os.getenv("LOCAL_AUTH_SEED_PASSWORD", "devpassword123")
        seed_name = os.getenv("LOCAL_AUTH_SEED_DISPLAY_NAME", "Blogify Dev")
        await auth_repo.create(
            email=seed_email,
            password_hash=self.hash_password(seed_password),
            display_name=seed_name,
        )

    async def authenticate(
        self,
        auth_repo: AuthUserRepository,
        *,
        email: str,
        password: str,
    ) -> Optional[LocalAuthUser]:
        user = await auth_repo.get_by_email(email)
        if user is None or not user.is_active:
            return None
        if not self.verify_password(password, user.password_hash):
            return None
        await auth_repo.touch_last_login(user.id)
        return LocalAuthUser(user_id=int(user.id), email=user.email, display_name=user.display_name)
