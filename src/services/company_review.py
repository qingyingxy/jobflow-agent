"""Explicit, user-scoped confirmation of company entries when auto proof is incomplete."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.domain.company_source import DiscoveredCompany
from src.services.company_discovery import (
    NON_COMPANY_ROOTS,
    clean_url,
    home_url,
    host,
    under_domain,
)
from src.services.recruitment_trust import ATS_DOMAINS, hiring_scope


def review_revision(row):
    content = [row.id, row.status, row.homepage_url, row.career_url, row.reason,
               row.attempts, str(row.last_checked_at), row.evidence]
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


async def confirm_company(session, *, user_id, company_id, homepage_url, career_url,
                          expected_revision, checker):
    row = session.scalar(select(DiscoveredCompany).where(
        DiscoveredCompany.id == company_id, DiscoveredCompany.user_id == user_id))
    if row is None:
        raise LookupError("公司候选不存在")
    if row.status != "pending" or review_revision(row) != expected_revision:
        raise RuntimeError("候选已更新，请刷新后重新查看并确认")
    homepage, career = clean_url(homepage_url.strip()), clean_url(career_url.strip())
    if not homepage or not home_url(homepage) or not career:
        raise ValueError("请填写有效的公司主页和招聘入口 HTTP(S) 地址")
    ats = any(under_domain(host(career), root) for root in ATS_DOMAINS)
    if (ats and not hiring_scope(career)) or (not ats and any(
        under_domain(host(career), root) for root in NON_COMPANY_ROOTS
    )):
        raise ValueError("招聘入口须为公司官网或企业专属招聘系统，不能使用共享平台首页")
    # Manual confirmation replaces ownership proof, never URL safety checks.
    await checker.validate(homepage)
    await checker.validate(career)
    session.refresh(row)
    if row.status != "pending" or review_revision(row) != expected_revision:
        raise RuntimeError("候选已更新，请刷新后重新查看并确认")
    if session.scalar(select(DiscoveredCompany.id).where(
        DiscoveredCompany.user_id == user_id, DiscoveredCompany.homepage_host == host(homepage),
        DiscoveredCompany.id != row.id,
    )):
        raise RuntimeError("该公司主页已有记录，请查看已有公司，避免重复确认")
    now = datetime.now(UTC)
    evidence = {**row.evidence, "manual_confirmation": {
        "confirmed_by": user_id, "confirmed_at": now.isoformat(),
        "homepage_url": homepage, "career_url": career,
        "previous_homepage_url": row.homepage_url, "previous_career_url": row.career_url,
        "automatic_reason": row.reason,
    }}
    # CAS also protects the interval between refresh and commit across workers.
    try:
        changed = session.execute(update(DiscoveredCompany).where(
            DiscoveredCompany.id == row.id, DiscoveredCompany.user_id == user_id,
            DiscoveredCompany.status == "pending", DiscoveredCompany.evidence == row.evidence,
            DiscoveredCompany.homepage_url == row.homepage_url,
            DiscoveredCompany.career_url == row.career_url,
            DiscoveredCompany.last_checked_at == row.last_checked_at,
        ).values(homepage_url=homepage, homepage_host=host(homepage), career_url=career,
                 status="manually_confirmed", reason="用户已人工确认入口，已加入后续分批查询",
                 evidence=evidence, verified_at=now, updated_at=now),
            execution_options={"synchronize_session": False})
        if not changed.rowcount:
            session.rollback()
            raise RuntimeError("候选已更新，请刷新后重新查看并确认")
        session.commit()
    except IntegrityError as error:
        session.rollback()
        raise RuntimeError("该公司主页已有记录，请刷新后查看") from error
    session.refresh(row)
    return row
