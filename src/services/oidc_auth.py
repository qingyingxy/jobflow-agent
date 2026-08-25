from __future__ import annotations

import hashlib
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Any
from urllib.parse import urlsplit

import httpx
import jwt
from jwt import InvalidTokenError, PyJWK, PyJWKSet


class OidcAuthenticationError(RuntimeError):
    def __init__(self, message: str, *, code: str = "invalid_access_token") -> None:
        super().__init__(message)
        self.code = code


class OidcAuthenticationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class OidcPrincipal:
    issuer: str
    subject: str


class OidcTokenVerifier:
    """Verify OIDC access tokens against a bounded, cached JWKS document."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        algorithms: tuple[str, ...],
        cache_seconds: int = 300,
        clock_skew_seconds: int = 30,
        http_timeout_seconds: float = 5.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_url = jwks_url
        self.algorithms = algorithms
        self.cache_seconds = cache_seconds
        self.clock_skew_seconds = clock_skew_seconds
        self.client = client or httpx.Client(
            timeout=http_timeout_seconds,
            follow_redirects=False,
        )
        self._keys: dict[str, PyJWK] = {}
        self._keys_loaded_at = 0.0
        self._unknown_key_refresh_at = float("-inf")
        self._lock = Lock()

    def verify(self, token: str) -> OidcPrincipal:
        if not token or len(token) > 16_384:
            raise OidcAuthenticationError("访问令牌格式无效")
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as error:
            raise OidcAuthenticationError("访问令牌格式无效") from error
        algorithm = str(header.get("alg") or "")
        key_id = str(header.get("kid") or "")
        if algorithm not in self.algorithms or not key_id:
            raise OidcAuthenticationError("访问令牌签名头无效")

        signing_key = self._signing_key(key_id, algorithm)
        try:
            claims = jwt.decode(
                token,
                key=signing_key.key,
                algorithms=[algorithm],
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.clock_skew_seconds,
                options={"require": ["exp", "iat", "sub"]},
            )
        except jwt.ExpiredSignatureError as error:
            raise OidcAuthenticationError(
                "访问令牌已过期",
                code="access_token_expired",
            ) from error
        except InvalidTokenError as error:
            raise OidcAuthenticationError("访问令牌验证失败") from error

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 512:
            raise OidcAuthenticationError("访问令牌缺少有效主体")
        return OidcPrincipal(issuer=self.issuer, subject=subject.strip())

    def _signing_key(self, key_id: str, algorithm: str) -> PyJWK:
        previous_loaded_at = self._keys_loaded_at
        keys = self._load_keys(force=False)
        key = keys.get(key_id)
        now = monotonic()
        if (
            key is None
            and self._keys_loaded_at == previous_loaded_at
            and now - self._unknown_key_refresh_at >= 10
        ):
            self._unknown_key_refresh_at = now
            keys = self._load_keys(force=True)
            key = keys.get(key_id)
        if key is None:
            raise OidcAuthenticationError("访问令牌签名密钥不存在")
        if key.algorithm_name != algorithm:
            raise OidcAuthenticationError("访问令牌算法与签名密钥不一致")
        return key

    def _load_keys(self, *, force: bool) -> dict[str, PyJWK]:
        with self._lock:
            fresh = (
                self._keys
                and monotonic() - self._keys_loaded_at < self.cache_seconds
            )
            if fresh and not force:
                return dict(self._keys)
            try:
                response = self.client.get(
                    self.jwks_url,
                    headers={"Accept": "application/json"},
                )
                response.raise_for_status()
                if len(response.content) > 1_048_576:
                    raise ValueError("JWKS response exceeds size limit")
                payload = response.json()
                raw_keys = payload.get("keys") if isinstance(payload, dict) else None
                if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 20:
                    raise ValueError("JWKS key count is invalid")
                jwk_set = PyJWKSet.from_dict(payload)
                usable_keys = [
                    key
                    for key in jwk_set.keys
                    if isinstance(key.key_id, str)
                    and key.key_id
                    and key.public_key_use in {None, "sig"}
                    and key.algorithm_name in self.algorithms
                ]
                if len({key.key_id for key in usable_keys}) != len(usable_keys):
                    raise ValueError("JWKS contains duplicate key ids")
                parsed = {key.key_id: key for key in usable_keys}
                if not parsed:
                    raise ValueError("JWKS contains no keyed signing material")
            except (httpx.HTTPError, ValueError, jwt.PyJWTError) as error:
                raise OidcAuthenticationUnavailable(
                    "身份提供方签名密钥暂时不可用"
                ) from error
            self._keys = parsed
            self._keys_loaded_at = monotonic()
            return dict(parsed)


def oidc_internal_user_id(principal: OidcPrincipal) -> str:
    digest = hashlib.sha256(
        f"{principal.issuer}\0{principal.subject}".encode()
    ).hexdigest()
    return f"oidc_{digest[:48]}"


def configured_algorithms(value: str) -> tuple[str, ...]:
    allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
    algorithms = tuple(
        dict.fromkeys(item.strip().upper() for item in value.split(",") if item.strip())
    )
    if not algorithms or any(item not in allowed for item in algorithms):
        raise ValueError("OIDC_ALGORITHMS 只能包含受支持的非对称签名算法")
    return algorithms


def validate_auth_configuration(settings: Any) -> None:
    mode = str(settings.auth_mode).casefold()
    deployed = str(settings.app_env).casefold() in {"staging", "production"}
    if mode not in {"local", "oidc", "trusted_header"}:
        raise ValueError("AUTH_MODE 必须是 local、oidc 或 trusted_header")
    if deployed and mode == "local":
        raise ValueError("staging/production 禁止使用 local 身份模式")
    if deployed and settings.allow_insecure_user_header:
        raise ValueError("staging/production 必须关闭 ALLOW_INSECURE_USER_HEADER")
    if mode == "trusted_header":
        if not str(settings.trusted_identity_header or "").strip():
            raise ValueError("trusted_header 模式缺少 TRUSTED_IDENTITY_HEADER")
        return
    if mode != "oidc":
        return

    required = {
        "OIDC_ISSUER": settings.oidc_issuer,
        "OIDC_AUDIENCE": settings.oidc_audience,
        "OIDC_JWKS_URL": settings.oidc_jwks_url,
    }
    missing = [name for name, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(f"oidc 模式缺少配置：{', '.join(missing)}")
    configured_algorithms(settings.oidc_algorithms)
    if not 30 <= settings.oidc_jwks_cache_seconds <= 86_400:
        raise ValueError("OIDC_JWKS_CACHE_SECONDS 必须在 30 到 86400 之间")
    if not 0 <= settings.oidc_clock_skew_seconds <= 300:
        raise ValueError("OIDC_CLOCK_SKEW_SECONDS 必须在 0 到 300 之间")
    if not 0.1 <= settings.oidc_http_timeout_seconds <= 30:
        raise ValueError("OIDC_HTTP_TIMEOUT_SECONDS 必须在 0.1 到 30 之间")
    if deployed:
        for name in ("oidc_issuer", "oidc_jwks_url"):
            url = urlsplit(str(getattr(settings, name)))
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError(f"staging/production 的 {name} 必须是 HTTPS URL")
