from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Literal

from src.domain.graduation import (
    cohort_conflict_sources,
    cohort_source_fragments,
    simple_cohort_years,
)
from src.services.discovery_sources import JobStub
from src.services.job_header_facts import (
    effective_job_locations,
    recruitment_type_conflicts,
)
from src.services.search_constraints import select_term_groups
from src.services.search_vocabulary import _LOCATION_GROUPS, _ROLE_GROUPS

MatchTier = Literal["strict", "expanded"]


@dataclass(frozen=True)
class DiscoveryJobMatch:
    match_tier: MatchTier
    mismatch_reasons: tuple[str, ...]
    mismatch_labels: tuple[str, ...]
    filter_status: Literal["matched", "pending", "excluded"] = "pending"
    checks: tuple[dict[str, object], ...] = ()
    preference_score: int = 0
    body_verified: bool = False
    decision_policy: str = "hybrid"
    decision_version: str = "query-filters-v13-duty-grounded-scope"

    @property
    def review_status(self) -> Literal["recommended", "pending", "excluded"]:
        """Viewing priority is independent of strict eligibility and search quotas."""
        required = [c for c in self.checks if c.get("required", True)]
        if self.filter_status == "excluded" or any(c["status"] == "excluded" for c in required):
            return "excluded"
        if self.filter_status == "matched":
            return "recommended"
        if not self.body_verified:
            return "pending"
        # Missing cohorts are reviewable; uninterpreted eligibility clauses may
        # still contain a conflict and must not become a recommendation.
        if any(c["field"] == "graduation_year" and c["status"] == "pending"
               and c.get("diagnosis") != "source_missing" for c in required):
            return "pending"
        # Only cohort and availability may remain unknown. A missing direction,
        # city, recruitment type or other hard constraint must stay in review.
        core = [c for c in required if c["field"] not in {"graduation_year", "availability"}]
        if core and all(c["status"] == "matched" for c in core):
            return "recommended"
        return "pending"

    def as_dict(self, *, job_posting_id: str) -> dict[str, object]:
        return {
            "job_posting_id": job_posting_id,
            "match_tier": self.match_tier,
            "mismatch_reasons": list(self.mismatch_reasons),
            "mismatch_labels": list(self.mismatch_labels),
            "filter_status": self.filter_status,
            "review_status": self.review_status,
            "review_version": "view-priority-v1",
            "checks": list(self.checks),
            "filter_version": self.decision_version,
            "decision_policy": self.decision_policy,
            "preference_score": self.preference_score,
        }


def apply_posting_availability(match: DiscoveryJobMatch, job, *, now=None) -> DiscoveryJobMatch:
    """Use the same availability gate for saved results and live search quotas."""
    now = now or datetime.now(UTC)
    match = replace(match, body_verified=job.verification_status in {"VERIFIED_OFFICIAL", "VERIFIED_SOURCE"})
    verified = job.last_verified_at
    if verified and verified.tzinfo is None:
        verified = verified.replace(tzinfo=UTC)
    from src.services.recruitment_context import current_batch_availability

    batch_status = current_batch_availability(getattr(job, "recruitment_context", {}), job.source_url or "", now=now)
    closed = job.availability_status == "CLOSED" or batch_status.get("value") == "CLOSED"
    availability_checked = getattr(job, "last_availability_checked_at", None) or verified
    if availability_checked and availability_checked.tzinfo is None:
        availability_checked = availability_checked.replace(tzinfo=UTC)
    stale = not verified or now - verified > timedelta(days=7) or not availability_checked or now - availability_checked > timedelta(days=7)
    uncertain = (
        job.availability_status != "ACTIVE"
        or job.verification_status == "LEGACY_UNVERIFIED"
    )
    if not (closed or stale or uncertain):
        return match
    status = "excluded" if closed else "pending"
    reason = (
        "关联招聘批次已结束或已过投递截止日期" if closed and job.availability_status != "CLOSED"
        else "岗位已关闭" if closed
        else "开放状态待更新：尚未核验或核验已超过7天" if stale
        else "开放状态未知" if match.body_verified
        else "岗位正文或开放状态待核实"
    )
    return replace(
        match,
        filter_status="excluded" if match.filter_status == "excluded" else status,
        match_tier="expanded",
        mismatch_reasons=(*match.mismatch_reasons, "closed" if closed else "stale"),
        mismatch_labels=(*match.mismatch_labels, reason),
        checks=(*match.checks, {
            "field": "availability", "status": status, "reason": reason,
            "evidence": [batch_status["source_text"]] if closed and batch_status.get("source_text") else [],
            "source_url": batch_status.get("source_url") or job.source_url or "",
        }),
    )


def classify_discovery_job(
    job: JobStub, *, query: str | None, role_review=None, conditions=None, primary=None
) -> DiscoveryJobMatch:
    """Filter verified page facts. Missing evidence never proves a conflict."""
    normalized_query = (query or "").casefold()
    reasons: list[str] = []
    labels: list[str] = []
    checks: list[dict[str, object]] = []

    def record(field, status, reason, evidence, code=None):
        checks.append(
            {
                "field": field,
                "status": status,
                "reason": reason,
                "evidence": evidence,
                "source_url": job.detail_url,
            }
        )
        if status != "matched":
            reasons.append(code or field)
            labels.append(reason)

    if conditions is None:
        conditions = search_filter_conditions(query)
    else:
        from src.domain.search_goal import SearchGoalConditions
        from src.services.search_intent import conditions_query

        conditions = SearchGoalConditions.model_validate(conditions).model_dump()
        # Every semantic helper consumes the same effective, editable scope.
        # The original input may no longer agree after a user edits fields.
        query = conditions_query(SearchGoalConditions(**conditions))
        normalized_query = query.casefold()
    from src.services.search_vocabulary import location_aliases

    wanted_locations = [location_aliases(v) for v in conditions["locations"]]
    denied_locations = [location_aliases(v) for v in conditions["excluded_locations"]]
    preferred_locations = [
        location_aliases(v) for v in conditions["preferred_locations"]
    ]
    preference_score = 0
    if wanted_locations or denied_locations:
        locations = effective_job_locations(job)
        location_text = " ".join(locations).casefold()
        known = [
            g
            for g in dict.fromkeys(
                (*_LOCATION_GROUPS, *wanted_locations, *denied_locations)
            )
            if any(_contains(location_text, t) for t in g)
        ]
        complete = all(
            any(_contains(location.casefold(), t) for g in known for t in g)
            for location in locations
        )
        if not known:
            record("location", "pending", "地点待确认", locations)
        elif all(g in denied_locations for g in known):
            record(
                "location",
                "excluded" if complete else "pending",
                "地点在明确排除范围内" if complete else "其他可选地点待确认",
                locations,
                "excluded_location" if complete else "location",
            )
        elif wanted_locations and not any(
            _contains(location_text, t) for g in wanted_locations for t in g
        ):
            uncertain = not complete
            record(
                "location",
                "pending" if uncertain else "excluded",
                "地点待确认" if uncertain else "地点不匹配",
                locations,
            )
        else:
            record("location", "matched", "已确认地点符合搜索条件", locations)

    if preferred_locations:
        locations = effective_job_locations(job)
        preference_score = int(
            any(
                _contains(" ".join(locations).casefold(), term)
                for group in preferred_locations
                for term in group
            )
        )
        checks.append(
            {
                "field": "preferred_location",
                "status": "matched",
                "reason": "命中优先地点，优先展示"
                if preference_score
                else "未命中优先地点，仍可展示",
                "evidence": locations,
                "source_url": job.detail_url,
                "required": False,
            }
        )

    type_groups = (
        ("校招", "校园招聘", "应届", "应届生"),
        ("实习", "internship", "intern"),
        ("社招", "社会招聘", "正式岗", "全职", "full-time"),
    )
    wanted_types = [g for g in type_groups if g[0] in conditions["job_types"]]
    denied_types = [g for g in type_groups if g[0] in conditions["excluded_job_types"]]
    type_names = dict(zip(type_groups, ("campus", "internship", "full_time")))
    if wanted_types or denied_types:
        evidence = [job.job_type] if job.job_type else []
        conflicts = recruitment_type_conflicts(job)
        if conflicts:
            record(
                "job_type",
                "pending",
                "招聘类型标签与岗位原文冲突，待核实",
                [*evidence, *conflicts],
            )
        elif job.job_type in {None, "unknown"}:
            record("job_type", "pending", "招聘类型待确认", evidence)
        elif job.job_type in {type_names[g] for g in denied_types}:
            record(
                "job_type",
                "excluded",
                "招聘类型在明确排除范围内",
                evidence,
                "excluded_job_type",
            )
        elif wanted_types and job.job_type not in {type_names[g] for g in wanted_types}:
            _, label = _expected_job_types(" ".join(g[0] for g in wanted_types))
            record("job_type", "excluded", label, evidence)
        else:
            record("job_type", "matched", "已确认招聘类型符合搜索条件", evidence)

    excluded_roles = [
        next((aliases for aliases, _ in _ROLE_GROUPS if role in aliases), (role,))
        for role in conditions["excluded_roles"]
    ]
    requested_roles = requested_role_terms(query, conditions=conditions)
    ai_terms = ("ai", "人工智能", "artificial intelligence")
    _, excluded_ai = select_term_groups(normalized_query, [ai_terms])
    from src.services.job_role_review import (
        duty_text,
        local_duty_evidence,
        software_domain_conflict,
        valid_review,
    )

    role_text = "\n".join([job.title or "", duty_text(job)])
    accepted_review = valid_review(role_review, job, query)
    title = (job.title or "").casefold()
    denied_terms = [t for aliases in excluded_roles for t in aliases]
    if excluded_ai:
        denied_terms.extend(ai_terms)
    if requested_roles or denied_terms:
        hits = [
            term
            for terms in requested_roles
            for term in terms
            if _contains(role_text.casefold(), term)
        ]
        mixed_boundary = mixed_frontend_boundary(job, denied_terms)
        direct_evidence = local_duty_evidence(job, query)
        domain_conflict = software_domain_conflict(job, query)
        if mixed_boundary:
            status, evidence = mixed_boundary
            record(
                "role",
                status,
                "岗位必须承担已排除的前端职责"
                if status == "excluded"
                else "前后端方向可选或职责不明确，待确认",
                evidence,
                "excluded_role" if status == "excluded" else "role",
            )
        elif any(_contains(title, term) for term in denied_terms):
            record(
                "role",
                "excluded",
                "岗位方向在明确排除范围内",
                [job.title],
                "excluded_role",
            )
        elif domain_conflict:
            record(
                "role",
                "excluded",
                "岗位职责为芯片设计流程，未承担目标软件前后端研发",
                domain_conflict,
            )
            checks[-1]["method"] = "local_domain"
        elif accepted_review:
            decision = accepted_review["decision"]
            record("role", decision["status"], decision["reason"], decision["evidence"])
        elif direct_evidence and not local_role_needs_review(job, requested_roles):
            record("role", "matched", "实际职责明确覆盖目标方向", direct_evidence)
            checks[-1]["method"] = "local_duties"
        elif requested_roles and not hits:
            record("role", "pending", "正文尚未确认目标方向", [])
        elif denied_terms and not title:
            record("role", "pending", "岗位名称缺失，排除方向待核实", [])
        elif local_role_needs_review(job, requested_roles):
            record(
                "role", "pending", "关键词或岗位标题不足以确认目标研发职责", [job.title]
            )
        elif requested_roles:
            record(
                "role", "pending", "方向关键词尚未绑定实际职责，待语义复核",
                _source_quotes(role_text, hits)[:3],
            )
        else:
            record(
                "role",
                "matched",
                "岗位内容包含目标方向：" + "、".join(dict.fromkeys(hits))
                if hits
                else "岗位名称未命中排除方向",
                _source_quotes(role_text, hits)[:3] if hits else [job.title],
            )

    for role in conditions["preferred_roles"]:
        evidence = local_duty_evidence(job, f"岗位方向：{role}")
        preference_score += int(bool(evidence))
        checks.append({
            "field": "preferred_role", "status": "matched", "required": False,
            "reason": f"实际职责覆盖优先方向：{role}" if evidence else f"优先方向尚未确认：{role}，仍可展示",
            "evidence": evidence, "source_url": job.detail_url,
        })

    years = conditions["graduation_years"]
    if years:
        # A season title or date is not an eligibility cohort. Keep the complete
        # sentence so regional qualifications and ranges cannot be dropped.
        fragments = cohort_source_fragments(job.raw_content or "", title=job.title)
        from src.services.recruitment_context import cohort_context

        fragments, from_batch = cohort_context(job, fragments)
        # A recruitment-season header is not eligibility. It also must not
        # obscure an explicit, matching graduation requirement below it.
        explicit = [simple_cohort_years(s) for s in fragments if simple_cohort_years(s)]
        if explicit:
            fragments = [s for s in fragments if not (
                re.fullmatch(r"(?:招聘项目[:：]\s*)?(20\d{2})\s*(?:校园招聘|校招)", s.strip())
                and all(years == {int(re.search(r"20\d{2}", s)[0])} for years in explicit)
            )]
        simple = [_simple_search_cohort(s) for s in fragments]
        cohorts = {
            int(y)
            for sentence in simple
            if sentence
            for y in re.findall(r"20\d{2}", sentence)
        }
        certain = bool(fragments) and all(simple) and len(set(simple)) == 1
        if certain:
            conflicts = cohort_conflict_sources(
                fragments[0], job.raw_content or "", title=job.title
            )
            if conflicts:
                fragments = list(dict.fromkeys([*fragments, *conflicts]))
                certain = False
        if re.search(
            r"(?:不考虑|排除|不接受)[^，,；;。\n]*20\d{2}|20\d{2}[^，,；;。\n]*(?:至|到|[-~～])[^，,；;。\n]*20\d{2}",
            normalized_query,
        ):
            certain = False
        if certain and set(years) & cohorts:
            record("graduation_year", "matched", "岗位明确接受目标届别", fragments)
        elif certain and not set(years) & cohorts:
            record(
                "graduation_year",
                "excluded",
                "岗位明确接受的届别不包含目标届别",
                fragments,
            )
        else:
            record(
                "graduation_year",
                "pending",
                "适用届别待核实：原文含有附加条件或尚未完成理解" if fragments
                else "当前岗位正文及已关联批次未写明适用届别",
                fragments,
            )
            checks[-1]["diagnosis"] = "ambiguous" if fragments else "source_missing"
        if from_batch:
            checks[-1]["source_url"] = job.recruitment_context["source_url"]
            checks[-1]["snapshot_id"] = job.recruitment_context.get("snapshot_id")
            checks[-1]["method"] = "associated_recruitment_batch"
    for keyword in conditions["keywords"]:
        quotes = _source_quotes(
            "\n".join([job.title or "", job.raw_content or ""]), [keyword]
        )
        record(
            "keyword",
            "matched" if quotes else "pending",
            f"岗位内容包含关键词：{keyword}" if quotes else f"关键词待核实：{keyword}",
            quotes[:2],
        )
    for keyword in conditions["preferred_keywords"]:
        quotes = _source_quotes(
            "\n".join([job.title or "", job.raw_content or ""]), [keyword]
        )
        preference_score += int(bool(quotes))
        checks.append(
            {
                "field": "preferred_keyword",
                "status": "matched",
                "reason": f"命中优先关键词：{keyword}"
                if quotes
                else f"未命中优先关键词：{keyword}，仍可展示",
                "evidence": quotes[:2],
                "source_url": job.detail_url,
                "required": False,
            }
        )
    if conditions["pending_conditions"]:
        record(
            "additional",
            "pending",
            "附加条件待核实：" + "、".join(conditions["pending_conditions"]),
            [],
        )

    from src.services.source_understanding import (
        VERSION,
        ai_policy_enabled,
        checked_decisions,
        requested_fields,
    )

    if primary is None:
        primary = ai_policy_enabled() or (job.recruitment_context or {}).get("understanding_policy") == "ai"
    interpreted = checked_decisions(job, conditions, primary=primary)
    if primary:
        # Rules remain useful for retrieval hints. They do not pre-empt the
        # source-bound semantic decision or hide a job awaiting interpretation.
        targets = requested_fields(conditions)
        decisions = {field: interpreted.get(field, {
            "field": field, "status": "pending", "reason": "原文已保存，等待当前版本AI理解（旧判断不再沿用）",
            "evidence": [], "source_url": job.detail_url, "diagnosis": "not_extracted",
            "method": "source_semantics", "version": VERSION,
        }) for field in targets}
        seen = {c["field"] for c in checks}
        checks = [decisions.get(c["field"], c) for c in checks]
        checks.extend(decisions[field] for field in targets if field not in seen)
    elif interpreted:
        checks = [interpreted.get(c["field"], c) if c["status"] == "pending" else c for c in checks]
    if interpreted or primary:
        reasons = [c["field"] for c in checks if c["status"] != "matched"]
        labels = [c["reason"] for c in checks if c["status"] != "matched"]
    for check in checks:
        if check["status"] == "pending" and check["field"] in {"location", "job_type", "graduation_year", "role"}:
            check.setdefault("diagnosis", "ambiguous" if check["evidence"] else "not_extracted")

    states = {check["status"] for check in checks}
    status = (
        "excluded"
        if "excluded" in states
        else "pending"
        if "pending" in states
        else "matched"
    )
    return DiscoveryJobMatch(
        match_tier="expanded" if reasons else "strict",
        mismatch_reasons=tuple(reasons),
        mismatch_labels=tuple(labels),
        filter_status=status,
        checks=tuple(checks),
        preference_score=preference_score,
        decision_policy="ai" if primary else "hybrid",
        decision_version=VERSION if primary else "query-filters-v13-duty-grounded-scope",
    )


def requested_role_terms(query, *, conditions=None):
    """Share the positive direction scope with model-exclusion validation."""
    text = (query or "").casefold()
    roles = (conditions if conditions is not None else search_filter_conditions(query))[
        "roles"
    ]
    terms = [
        next(
            (values for aliases, values in _ROLE_GROUPS if role in aliases),
            ("ai", "人工智能", "artificial intelligence") if role == "ai" else (role,),
        )
        for role in roles
    ]
    if re.search(r"(?:大模型|大语言模型|llm)\s*(?:应用|application)", text):
        terms = [
            (
                "大模型应用",
                "大语言模型应用",
                "llm application",
                "llm应用",
                "rag",
                "检索增强",
                "agent",
                "智能体",
            )
            if "llm" in values or "ai应用" in values
            else values
            for values in terms
        ]
    return terms


def mixed_frontend_boundary(job, denied_terms):
    """A full-stack title alone does not prove mandatory frontend work."""
    if not any(t in denied_terms for t in ("前端", "frontend", "front-end")):
        return None
    title = (job.title or "").casefold()
    if not re.search(r"全栈|前后端|前端.*后端|后端.*前端|full.?stack", title):
        return None
    from src.services.job_role_review import duty_text

    duties = duty_text(job)
    if re.search(r"任选|二选一|可选|或后端|或前端|按方向|择一", title + "\n" + duties):
        return "pending", [job.title]
    evidence = [
        line.strip()
        for line in duties.splitlines()
        if re.search(r"负责|承担|主导|参与|持续跟进", line)
        and re.search(r"前后端|前端.{0,20}(?:开发|技术|研发)", line)
        and not re.search(r"不负责|无需|协同前端|与前端|加分|优先", line)
    ]
    return ("excluded", evidence) if evidence else ("pending", [job.title])


def local_role_needs_review(job, requested_roles):
    """Technical keywords in another function cannot alone prove an R&D role."""
    terms = {t for group in requested_roles for t in group}
    from src.services.job_role_review import (
        SPECIFIC_DIRECTION_TERMS,
        specific_direction_needs_evidence,
    )

    if (
        terms
        and terms
        <= (
            SPECIFIC_DIRECTION_TERMS
            | {"后端", "backend", "back-end", "前端", "frontend", "front-end"}
        )
        and specific_direction_needs_evidence(job, " ".join(terms))
    ):
        return True
    return role_title_needs_review(job, requested_roles)


def role_title_needs_review(job, requested_roles):
    """A planning/design title needs semantic interpretation of R&D wording."""
    terms = {t for group in requested_roles for t in group}
    engineering = {
        "ai agent",
        "agent",
        "智能体",
        "rag",
        "检索增强",
        "后端",
        "backend",
        "前端",
        "frontend",
        "算法",
        "algorithm",
        "大模型应用",
        "llm应用",
    }
    if not terms & engineering or terms & {"产品", "product"}:
        return False
    return bool(
        re.search(
            r"产品(?:经理|运营|实习生|助理)|校园大使|数据策略|(?:销售|商务|市场|人力资源|行政|运营)(?:经理|专员|顾问|实习生)|"
            r"(?:产品|视觉|交互|平面|UI|UX|用户体验)设计师|"
            r"\b(?:product manager|talent partner|recruiter)\b",
            job.title or "",
            re.IGNORECASE,
        )
    ) or bool(re.search(r"^官网职能分类：[^\n]*(?:运营|产品|销售|市场)",
                        job.raw_content or "", re.MULTILINE))


def _simple_search_cohort(sentence):
    years = simple_cohort_years(sentence)
    return ",".join(map(str, sorted(years))) if years else None


def _source_quotes(text: str, terms: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            sentence.strip()
            for sentence in re.split(r"[。；;\n]", text)
            if any(_contains(sentence.casefold(), term.casefold()) for term in terms)
        )
    )


def search_filter_conditions(query: str | None) -> dict[str, object]:
    from src.services.search_intent import parse_conditions

    return parse_conditions(query).model_dump()


def _expected_job_types(query: str) -> tuple[set[str], str]:
    campus = _contains_any(query, ("校招", "校园招聘", "应届", "应届生"))
    internship = _contains_any(query, ("实习", "internship", "intern"))
    if campus and internship:
        return {"campus", "internship"}, "非校招或实习"
    if campus:
        return {"campus"}, "非校招"
    if internship:
        return {"internship"}, "非实习"
    if _contains_any(query, ("社招", "社会招聘", "正式岗", "全职", "full-time")):
        return {"full_time"}, "非正式岗"
    return set(), "招聘类型不匹配"


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(_contains(text, term) for term in terms)


def _contains(text: str, term: str) -> bool:
    normalized_term = term.casefold()
    if re.fullmatch(r"[a-z0-9][a-z0-9 .+'-]*", normalized_term):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])",
                text,
            )
        )
    return normalized_term in text
