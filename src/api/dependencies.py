import re
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.config import get_settings
from src.infrastructure.database import get_session
from src.services.oidc_auth import (
    OidcAuthenticationError,
    OidcAuthenticationUnavailable,
    OidcTokenVerifier,
    configured_algorithms,
    oidc_internal_user_id,
    validate_auth_configuration,
)


@lru_cache
def get_oidc_verifier() -> OidcTokenVerifier:
    settings = get_settings()
    return OidcTokenVerifier(
        issuer=str(settings.oidc_issuer),
        audience=str(settings.oidc_audience),
        jwks_url=str(settings.oidc_jwks_url),
        algorithms=configured_algorithms(settings.oidc_algorithms),
        cache_seconds=settings.oidc_jwks_cache_seconds,
        clock_skew_seconds=settings.oidc_clock_skew_seconds,
        http_timeout_seconds=settings.oidc_http_timeout_seconds,
    )


def get_current_user_id(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve local identity or a trusted gateway subject in deployed environments."""

    settings = get_settings()
    try:
        validate_auth_configuration(settings)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "authentication_not_configured",
                "message": str(error),
            },
        ) from error
    mode = settings.auth_mode.casefold()
    if mode == "oidc":
        authorization = (request.headers.get("Authorization") or "").strip()
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.casefold() != "bearer" or not token.strip():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "authentication_required",
                    "message": "请求缺少 Bearer 访问令牌",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        try:
            principal = get_oidc_verifier().verify(token.strip())
        except OidcAuthenticationUnavailable as error:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "identity_provider_unavailable",
                    "message": str(error),
                },
            ) from error
        except OidcAuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": error.code, "message": str(error)},
                headers={"WWW-Authenticate": "Bearer error=\"invalid_token\""},
            ) from error
        candidate = oidc_internal_user_id(principal)
    elif mode == "trusted_header":
        header_name = (settings.trusted_identity_header or "").strip()
        candidate = (request.headers.get(header_name) or "").strip()
        if not candidate:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "authenticated_identity_required",
                    "message": "请求缺少可信身份",
                },
            )
    else:
        candidate = (x_user_id or settings.default_user_id).strip()
    if not re.fullmatch(r"[A-Za-z0-9._:@+|=-]{1,64}", candidate):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_user_identity", "message": "用户身份格式无效"},
        )
    return candidate


CurrentUserId = Annotated[str, Depends(get_current_user_id)]
DatabaseSession = Annotated[Session, Depends(get_session)]
