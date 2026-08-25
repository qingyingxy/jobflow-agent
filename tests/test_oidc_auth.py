from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from src.api import dependencies
from src.config import Settings
from src.main import app
from src.services.oidc_auth import (
    OidcAuthenticationError,
    OidcAuthenticationUnavailable,
    OidcTokenVerifier,
    oidc_internal_user_id,
    validate_auth_configuration,
)

ISSUER = "https://identity.example.com"
AUDIENCE = "jobflow-api"
JWKS_URL = f"{ISSUER}/.well-known/jwks.json"


def _key_material(key_id: str = "fixture-key"):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(RSAAlgorithm.to_jwk(private_key.public_key()))
    jwk.update({"kid": key_id, "use": "sig", "alg": "RS256"})
    return private_key, jwk


def _token(
    private_key,
    *,
    key_id: str = "fixture-key",
    issuer: str = ISSUER,
    audience: str = AUDIENCE,
    subject: str = "provider-user-42",
    issued_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "iss": issuer,
            "aud": audience,
            "sub": subject,
            "iat": issued_at or now,
            "exp": expires_at or now + timedelta(minutes=5),
        },
        private_key,
        algorithm="RS256",
        headers={"kid": key_id},
    )


def _verifier(
    jwk: dict[str, object],
    calls: list[str] | None = None,
    *,
    algorithms: tuple[str, ...] = ("RS256",),
):
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(str(request.url))
        return httpx.Response(200, json={"keys": [jwk]})

    return OidcTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        algorithms=algorithms,
        cache_seconds=300,
        clock_skew_seconds=0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_oidc_verifier_validates_signature_claims_and_caches_jwks() -> None:
    private_key, jwk = _key_material()
    calls: list[str] = []
    verifier = _verifier(jwk, calls)
    encoded = _token(private_key)

    first = verifier.verify(encoded)
    second = verifier.verify(encoded)

    assert first == second
    assert first.issuer == ISSUER
    assert first.subject == "provider-user-42"
    assert len(calls) == 1
    assert oidc_internal_user_id(first).startswith("oidc_")
    assert len(oidc_internal_user_id(first)) == 53


@pytest.mark.parametrize(
    ("token_factory", "expected_code"),
    [
        (
            lambda key: _token(key, audience="another-api"),
            "invalid_access_token",
        ),
        (
            lambda key: _token(key, issuer="https://forged.example.com"),
            "invalid_access_token",
        ),
        (
            lambda key: _token(
                key,
                issued_at=datetime.now(UTC) - timedelta(minutes=10),
                expires_at=datetime.now(UTC) - timedelta(minutes=5),
            ),
            "access_token_expired",
        ),
    ],
)
def test_oidc_verifier_rejects_invalid_registered_claims(
    token_factory,
    expected_code: str,
) -> None:
    private_key, jwk = _key_material()

    with pytest.raises(OidcAuthenticationError) as rejected:
        _verifier(jwk).verify(token_factory(private_key))

    assert rejected.value.code == expected_code


def test_oidc_verifier_rejects_forged_signature_and_unknown_key() -> None:
    trusted_key, jwk = _key_material()
    forged_key, _ = _key_material()
    calls: list[str] = []
    verifier = _verifier(jwk, calls)

    with pytest.raises(OidcAuthenticationError):
        verifier.verify(_token(forged_key))
    with pytest.raises(OidcAuthenticationError):
        verifier.verify(_token(trusted_key, key_id="rotated-key"))
    with pytest.raises(OidcAuthenticationError):
        verifier.verify(_token(trusted_key, key_id="another-unknown-key"))

    assert len(calls) == 2


def test_oidc_verifier_fails_closed_when_jwks_is_unavailable() -> None:
    private_key, _ = _key_material()
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(503, text="unavailable")
        )
    )
    verifier = OidcTokenVerifier(
        issuer=ISSUER,
        audience=AUDIENCE,
        jwks_url=JWKS_URL,
        algorithms=("RS256",),
        client=client,
    )

    with pytest.raises(OidcAuthenticationUnavailable):
        verifier.verify(_token(private_key))


def test_oidc_verifier_rejects_jwk_algorithm_mismatch() -> None:
    private_key, jwk = _key_material()
    jwk["alg"] = "RS512"

    with pytest.raises(OidcAuthenticationError):
        _verifier(jwk, algorithms=("RS256", "RS512")).verify(_token(private_key))


@pytest.mark.asyncio
async def test_oidc_api_ignores_forged_user_header_and_requires_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key, jwk = _key_material()
    verifier = _verifier(jwk)
    settings = Settings(
        app_env="production",
        auth_mode="oidc",
        allow_insecure_user_header=False,
        oidc_issuer=ISSUER,
        oidc_audience=AUDIENCE,
        oidc_jwks_url=JWKS_URL,
    )
    monkeypatch.setattr(dependencies, "get_settings", lambda: settings)
    monkeypatch.setattr(dependencies, "get_oidc_verifier", lambda: verifier)
    encoded = _token(private_key)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.get(
            "/api/private-profile",
            headers={"X-User-ID": "forged-user"},
        )
        accepted = await client.get(
            "/api/private-profile",
            headers={
                "X-User-ID": "forged-user",
                "Authorization": f"Bearer {encoded}",
            },
        )

    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "authentication_required"
    assert missing.headers["www-authenticate"] == "Bearer"
    assert accepted.status_code == 200
    assert accepted.json()["user_id"] == oidc_internal_user_id(
        verifier.verify(encoded)
    )
    assert accepted.json()["user_id"] != "forged-user"


def test_deployed_auth_configuration_is_fail_closed() -> None:
    with pytest.raises(ValueError, match="禁止使用 local"):
        validate_auth_configuration(
            Settings(
                app_env="production",
                auth_mode="local",
                allow_insecure_user_header=False,
            )
        )
    with pytest.raises(ValueError, match="HTTPS"):
        validate_auth_configuration(
            Settings(
                app_env="production",
                auth_mode="oidc",
                allow_insecure_user_header=False,
                oidc_issuer="http://identity.example.com",
                oidc_audience=AUDIENCE,
                oidc_jwks_url="http://identity.example.com/jwks.json",
            )
        )
