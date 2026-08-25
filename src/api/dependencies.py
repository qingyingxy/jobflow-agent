import re
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from src.config import get_settings
from src.infrastructure.database import get_session


def get_current_user_id(
    request: Request,
    x_user_id: Annotated[str | None, Header()] = None,
) -> str:
    """Resolve local identity or a trusted gateway subject in deployed environments."""

    settings = get_settings()
    deployed = settings.app_env.casefold() in {"staging", "production"}
    if deployed:
        header_name = (settings.trusted_identity_header or "").strip()
        if settings.allow_insecure_user_header or not header_name:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "trusted_identity_not_configured",
                    "message": "部署环境尚未配置可信身份网关",
                },
            )
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
