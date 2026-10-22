"""Review discovered companies independently of whether a search goal is selected."""

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.api.dependencies import CurrentUserId, DatabaseSession
from src.config import get_settings
from src.services.company_discovery import company_discovery_summary
from src.services.company_review import confirm_company
from src.services.url_reader import URLReaderError, URLSafetyChecker

router = APIRouter(prefix="/api/discovery/companies", tags=["company-sources"])


class CompanyConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    homepage_url: str = Field(min_length=8, max_length=2000)
    career_url: str = Field(min_length=8, max_length=2000)
    confirmed: Literal[True]
    expected_revision: str = Field(min_length=64, max_length=64)

    @field_validator("confirmed", mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if value is not True:
            raise ValueError("请明确确认已查看公司主页和招聘入口")
        return value


def confirmation_checker():
    settings = get_settings()
    return URLSafetyChecker(proxy_url=settings.url_fetch_proxy,
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)


@router.get("")
def list_companies(user_id: CurrentUserId, session: DatabaseSession):
    return company_discovery_summary(session, user_id)


@router.post("/{company_id}/confirm")
async def confirm_company_source(company_id: str, payload: CompanyConfirmation,
                                 user_id: CurrentUserId, session: DatabaseSession):
    try:
        row = await confirm_company(session, user_id=user_id, company_id=company_id,
            homepage_url=payload.homepage_url, career_url=payload.career_url,
            expected_revision=payload.expected_revision, checker=confirmation_checker())
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RuntimeError as error:
        if isinstance(error, URLReaderError):
            raise HTTPException(status_code=422, detail="地址未通过公开网址安全校验，请检查后重试") from error
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return next(item for item in company_discovery_summary(session, user_id) if item["id"] == row.id)
