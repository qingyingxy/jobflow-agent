"""Job-bound recruitment evidence. Supplemental pages never replace the JD."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, date, datetime, timedelta, timezone
from urllib.parse import parse_qs, urljoin, urlsplit

from src.domain.job import JobAvailabilityStatus
from src.services.job_detail_scope import DetailScopeError, _Page, _select_scope
from src.services.job_url import canonical_job_url
from src.services.url_reader import URLReaderError

_BATCH_LINK = re.compile(r"招聘批次|招聘项目|招聘公告|批次公告")
_OPEN = re.compile(
    r"^(?:岗位状态|职位状态|招聘状态|网申状态|批次状态)[:：]\s*(?:招聘中|正在招聘|在招|开放申请|接受申请|网申进行中|开放中|open|accepting applications)[。！.!]?$",
    re.IGNORECASE,
)
_CLOSED = re.compile(
    r"^(?:(?:该|此|本)?(?:职位|岗位)(?:已关闭|已下线|已结束|已停止招聘)(?:[，,]不再接受(?:投递|申请))?|(?:岗位状态|职位状态|招聘状态|网申状态|批次状态)[:：]\s*(?:已关闭|已结束|已下线|停止招聘)|招聘已结束|已结束|已关闭|停止招聘|不再接受(?:投递|申请)|no longer accepting applications)[。！.!]?$",
    re.IGNORECASE,
)
_APPLY = re.compile(
    r"^(?:投递岗位|申请职位|立即申请|立即投递|申请岗位|apply|apply now)$", re.IGNORECASE
)
_OPPO_PATH = re.compile(r"/university/oppo/campus/post/(\d+)/?$")


def oppo_detail_api(url):
    parsed = urlsplit(url)
    match = _OPPO_PATH.fullmatch(parsed.path)
    if parsed.scheme == "https" and parsed.netloc == "careers.oppo.com" and match:
        return f"https://careers.oppo.com/openapi/position/detail?id={match[1]}"
    return None


def captures_detail_api(response_url, page_url):
    from src.services.recruitment_templates import alibaba_detail_api

    expected = oppo_detail_api(page_url)
    return bool(expected and canonical_job_url(response_url) == expected) or alibaba_detail_api(response_url, page_url)


def _page(raw_html):
    page = _Page()
    page.feed(raw_html)
    return page


def _lines(root):
    from src.services.recruitment_semantics import labelled_fields

    # Leaf blocks avoid treating whole-page occurrences as status declarations.
    return list(dict.fromkeys([
        *(n.text() for n in root.walk() if len(n.text()) < 200),
        *(field.source_text for field in labelled_fields(root)),
    ]))


def _declared_status(scope, *, now=None):
    lines = _lines(scope) if scope else []
    closed = next((s for s in lines if _CLOSED.fullmatch(s)), None)
    opened = next((s for s in lines if _OPEN.fullmatch(s)), None)
    if closed:
        return {"value": "CLOSED", "source_text": closed}
    # Old announcements can still say "open" after their explicit deadline.
    windows = [s for s in lines if re.match(r"^(?:网申|投递|报名)时间[:：]", s)]
    if len(windows) > 1:
        return {
            "value": "UNKNOWN",
            "source_text": None,
            "reason": "存在多个投递时间范围，需确认当前批次",
            "time_uncertain": True,
        }
    window = windows[0] if windows else None
    if window:
        dates = re.findall(r"(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?", window)
        try:
            start, end = [date(*map(int, parts)) for parts in dates]
            current = (
                (now or datetime.now(UTC))
                .astimezone(timezone(timedelta(hours=8)))
                .date()
            )
            if end < start:
                raise ValueError("reversed_application_window")
            if current > end:
                return {"value": "CLOSED", "source_text": window}
            if current < start:
                return {
                    "value": "UNKNOWN",
                    "source_text": window,
                    "reason": "尚未到网申开始日期",
                    "time_uncertain": True,
                }
        except ValueError:
            return {
                "value": "UNKNOWN",
                "source_text": window,
                "reason": "投递时间范围尚无法确认",
                "time_uncertain": True,
            }
    return {
        "value": "ACTIVE" if opened else "UNKNOWN",
        "source_text": opened,
        "application_window": window if window else None,
    }


def detail_status(raw_html, *, url, now=None):
    """A readable JD or an apply control alone cannot prove an open position."""
    from src.services.lead_presentation import discovery_kind

    if discovery_kind(url) != "job":
        return {"value": "UNKNOWN", "reason": "不是具体岗位页"}
    page = _page(raw_html)
    try:
        scope, _ = _select_scope(page.root)
        has_job_scope = True
    except DetailScopeError:
        # Removed JDs may retain only a closure notice. Exclude related regions.
        from src.services.job_detail_scope import _titles

        scope = page.root if len(_titles(page.root)) <= 1 else None
        has_job_scope = False
    status = _declared_status(scope, now=now)
    if status["value"] == "ACTIVE" and not has_job_scope:
        status = {"value": "UNKNOWN", "source_text": None}
    return {
        **status,
        "source_url": url,
        "source_kind": "scoped_status",
        "reason": status.get("reason")
        or ("未见明确的岗位开放状态" if status["value"] == "UNKNOWN" else None),
    }


def _enabled_apply(raw_html):
    try:
        scope, _ = _select_scope(_page(raw_html).root)
    except DetailScopeError:
        return False
    for node in scope.walk():
        if (
            not _APPLY.fullmatch(node.text())
            or node.tag not in {"a", "button"}
            and node.attrs.get("role") != "button"
        ):
            continue
        disabled = False
        parent = node
        while parent:
            disabled |= (
                "disabled" in parent.attrs
                or parent.attrs.get("aria-disabled") == "true"
            )
            disabled |= bool(
                re.search(
                    r"(?:^|[\s_-])disabled(?:$|[\s_-])", parent.attrs.get("class", "")
                )
            )
            parent = parent.parent
        if not disabled:
            return True
    return False


def context_is_current(context, url, *, now=None):
    if (
        not context
        or context.get("status") != "verified"
        or context.get("job_url") != canonical_job_url(url)
    ):
        return False
    try:
        checked = datetime.fromisoformat(context["checked_at"])
        checked = checked.replace(tzinfo=UTC) if checked.tzinfo is None else checked
        return timedelta(0) <= (now or datetime.now(UTC)) - checked <= timedelta(days=7)
    except (ValueError, TypeError, KeyError):
        return False


def current_batch_availability(context, url, *, now=None):
    if not context_is_current(context, url, now=now):
        return {}
    batch = context.get("availability", {})
    if "valid_through" in batch:
        from src.services.recruitment_semantics import deadline_availability

        batch = {**batch, **deadline_availability(batch["valid_through"], now=now)}
    # Re-evaluate a saved application window even inside the freshness TTL.
    if batch.get("application_window"):
        from html import escape

        status = _declared_status(
            _page(
                f"<main><p>{escape(batch.get('source_text') or '')}</p><p>{escape(batch['application_window'])}</p></main>"
            ).root,
            now=now,
        )
        batch = {**batch, **status}
    return batch


def resolve_availability(raw_html, *, url, context=None, now=None):
    evidence = detail_status(raw_html, url=url, now=now)
    if evidence["value"] == "CLOSED":
        return evidence
    if evidence.get("time_uncertain"):
        return evidence
    if context_is_current(context, url, now=now):
        batch = current_batch_availability(context, url, now=now)
        if (
            batch.get("value") == "CLOSED"
            or batch.get("value") == "ACTIVE"
            and (context.get("association") == "official_job_payload" or _enabled_apply(raw_html))
        ):
            return {
                **batch,
                "source_kind": context["association"] if context.get("association") in {
                    "official_job_payload", "job_structured_data",
                } else "associated_batch",
                "batch_id": context.get("batch_id"),
                "snapshot_id": context.get("snapshot_id"),
            }
    return evidence


def cohort_context(job, fragments):
    """Only explicit eligibility text can fill missing cohort facts."""
    from src.domain.graduation import cohort_source_fragments, simple_cohort_years

    context = getattr(job, "recruitment_context", {})
    if not context_is_current(context, job.detail_url):
        return fragments, False
    supplement = cohort_source_fragments(context.get("eligibility_text", ""))
    if not fragments:
        return supplement, bool(supplement)
    # Batch qualifiers also apply to a job that already names a cohort. Do not
    # drop regional/date conditions just because a shorter label exists in JD.
    original = [simple_cohort_years(s) for s in fragments]
    extra = [simple_cohort_years(s) for s in supplement]
    if supplement and (
        not all(extra)
        or not all(original)
        or set().union(*original) != set().union(*extra)
    ):
        return list(dict.fromkeys([*fragments, *supplement])), True
    return fragments, False


async def collect_recruitment_context(
    *,
    raw_html,
    document,
    url,
    fetcher,
    is_official,
    save_snapshot,
    api_records=(),
    now=None,
):
    """At most two public GETs; no search, login or application actions."""
    now = now or datetime.now(UTC)
    base = {
        "job_url": canonical_job_url(url),
        "checked_at": now.isoformat(),
        "version": 1,
    }
    if not is_official(url):
        return {}

    async def read(target):
        from src.services.recruitment_trust import hiring_scope, within_scope

        if fetcher is None:
            raise URLReaderError("只复核已有正文，关联批次需另行读取", code="saved_body_only")
        scope = hiring_scope(url)
        if (
            (urlsplit(target).scheme, urlsplit(target).netloc)
            != (urlsplit(url).scheme, urlsplit(url).netloc)
            or scope
            and not within_scope(target, scope)
            or not is_official(target)
        ):
            raise ValueError("supplement_not_official")
        response = await fetcher.fetch(target)
        if canonical_job_url(response.final_url) != canonical_job_url(
            target
        ) or not is_official(response.final_url):
            raise ValueError("supplement_redirect_unconfirmed")
        raw = response.body.decode("utf-8", errors="replace")
        snapshot_id = save_snapshot(target, raw)
        return raw, snapshot_id

    async def collect():
        from src.services.recruitment_templates import template_context

        template = template_context(url=url, raw_html=raw_html, document=document,
            api_records=api_records, base=base, save_snapshot=save_snapshot)
        if template is not None:
            return template
        endpoint = oppo_detail_api(url)
        if endpoint:
            exact = [
                r for r in api_records if captures_detail_api(r.get("url", ""), url)
            ]
            if len(exact) == 1:
                raw = json.dumps(exact[0]["payload"], ensure_ascii=False)
                detail_snapshot = save_snapshot(endpoint, raw)
            else:
                raw, detail_snapshot = await read(endpoint)
            payload = json.loads(raw)
            data = payload.get("data") if isinstance(payload, dict) else None
            if (
                not isinstance(payload, dict)
                or payload.get("code") != 0
                or not isinstance(data, dict)
            ):
                raise ValueError("detail_payload_invalid")
            job_id = parse_qs(urlsplit(endpoint).query)["id"][0]
            if (
                str(data.get("idRecruitPosition")) != job_id
                or data.get("positionName") != document.title
            ):
                raise ValueError("detail_identity_conflict")
            project_url = "https://careers.oppo.com/openapi/position/project/list"
            raw, snapshot_id = await read(project_url)
            projects = json.loads(raw)
            if (
                not isinstance(projects, dict)
                or projects.get("code") != 0
                or not isinstance(projects.get("data"), list)
            ):
                raise ValueError("batch_payload_invalid")
            selected = [
                p
                for p in projects["data"]
                if isinstance(p, dict)
                and str(p.get("idRecruitProject")) == str(data.get("projectId"))
            ]
            if (
                len(selected) != 1
                or not data.get("projectId")
                or selected[0].get("projectName") != data.get("projectName")
            ):
                raise ValueError("batch_identity_conflict")
            batch = selected[0]
            return {
                **base,
                "status": "verified",
                "association": "official_job_project_id",
                "job_id": job_id,
                "batch_id": str(data["projectId"]),
                "batch_name": batch["projectName"],
                "source_url": project_url,
                "snapshot_id": snapshot_id,
                "detail_snapshot_id": detail_snapshot,
                "eligibility_text": batch.get("recruitRequire") or "",
                "recruitment_type": batch.get("recruitmentTypeName"),
                "availability": {
                    "value": "UNKNOWN",
                    "source_url": endpoint,
                    "raw_position_status": data.get("positionStatus"),
                    "reason": "官方接口提供状态码，但尚无可核实的开放语义；批次存在不等于开放投递",
                },
            }
        from src.services.recruitment_semantics import (
            BATCH_FIELDS,
            labelled_fields,
            structured_context,
        )

        try:
            scope, _ = _select_scope(_page(raw_html).root)
        except DetailScopeError:
            return structured_context(raw_html=raw_html, document=document, url=url,
                                      base=base, save_snapshot=save_snapshot, now=now) or {}
        links = {
            urljoin(url, n.attrs["href"]): n.text()
            for n in scope.walk()
            if n.tag == "a" and n.attrs.get("href") and _BATCH_LINK.search(n.text())
        }


        for field in labelled_fields(scope):
            if field.label in BATCH_FIELDS:
                for node in field.value_node.walk():
                    if node.tag == "a" and node.attrs.get("href"):
                        links[urljoin(url, node.attrs["href"])] = field.value
        if len(links) != 1:
            return (
                {**base, "status": "unconfirmed", "reason": "缺少唯一的岗位批次关联"}
                if links
                else (structured_context(raw_html=raw_html, document=document, url=url,
                                         base=base, save_snapshot=save_snapshot, now=now) or {})
            )
        target, label = next(iter(links.items()))
        raw, snapshot_id = await read(target)
        page = _page(raw)
        regions = [
            n
            for n in page.root.walk()
            if n.tag == "main" or n.attrs.get("role") == "main"
        ]
        if not regions:
            regions = [n for n in page.root.walk() if n.tag == "article"]
        if len(regions) != 1:
            raise ValueError("batch_scope_unconfirmed")
        # A batch announcement must not be a list of unrelated job cards.
        from src.services.job_detail_scope import _normalized_scope_text, _titles

        if len(_titles(regions[0])) > 1:
            raise ValueError("batch_scope_ambiguous")
        text = _normalized_scope_text(regions[0])
        if not re.search(r"招聘批次|招聘项目|招聘公告|校园招聘|应届生招聘", text):
            raise ValueError("batch_content_unconfirmed")
        availability = _declared_status(regions[0], now=now)
        return {
            **base,
            "status": "verified",
            "association": "job_scoped_batch_link",
            "batch_id": target,
            "batch_name": label,
            "source_url": target,
            "snapshot_id": snapshot_id,
            "eligibility_text": text,
            "availability": {**availability, "source_url": target},
        }

    try:
        async with asyncio.timeout(8):
            return await collect()
    except (URLReaderError, TimeoutError, ValueError, TypeError, KeyError) as error:
        return {
            **base,
            "status": "unconfirmed",
            "reason": getattr(error, "code", None) or type(error).__name__,
        }


def availability_status(evidence):
    return JobAvailabilityStatus(evidence["value"])
