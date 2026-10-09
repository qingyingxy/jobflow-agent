from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.domain.graduation import classify_graduation_condition
from src.services.discovery_sources import JobStub
from src.services.job_header_facts import effective_job_locations
from src.services.search_constraints import select_term_groups

MatchTier = Literal["strict", "expanded"]


@dataclass(frozen=True)
class DiscoveryJobMatch:
    match_tier: MatchTier
    mismatch_reasons: tuple[str, ...]
    mismatch_labels: tuple[str, ...]
    filter_status: Literal["matched", "pending", "excluded"] = "pending"
    checks: tuple[dict[str, object], ...] = ()

    def as_dict(self, *, job_posting_id: str) -> dict[str, object]:
        return {
            "job_posting_id": job_posting_id,
            "match_tier": self.match_tier,
            "mismatch_reasons": list(self.mismatch_reasons),
            "mismatch_labels": list(self.mismatch_labels),
            "filter_status": self.filter_status,
            "checks": list(self.checks),
            "filter_version": "query-filters-v3",
        }


_LOCATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("北京", "beijing"),
    ("上海", "shanghai"),
    ("深圳", "shenzhen"),
    ("广州", "guangzhou"),
    ("杭州", "hangzhou"),
    ("成都", "chengdu"),
    ("南京", "nanjing"),
    ("武汉", "wuhan"),
    ("苏州", "suzhou"),
    ("西安", "xi'an", "xian"),
    ("天津", "tianjin"),
    ("重庆", "chongqing"),
    ("厦门", "xiamen"),
    ("新加坡", "singapore"),
    ("香港", "hong kong"),
    ("圣何塞", "san jose"),
    ("西雅图", "seattle"),
)

_ROLE_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("ai应用", "ai 应用", "人工智能应用"),
        ("ai应用", "ai 应用", "人工智能应用", "agent", "智能体", "rag", "大模型"),
    ),
    (("agent", "智能体"), ("agent", "智能体")),
    (
        ("llm", "大模型", "大语言模型", "large language model"),
        (
            "llm",
            "大模型",
            "大语言模型",
            "large language model",
            "foundation model",
            "generative ai",
        ),
    ),
    (
        ("算法", "algorithm"),
        (
            "算法",
            "algorithm",
            "machine learning",
            "机器学习",
            "deep learning",
            "深度学习",
            "推荐",
            "搜索",
            "计算机视觉",
        ),
    ),
    (("rag", "检索增强"), ("rag", "检索增强")),
    (("nlp", "自然语言处理"), ("nlp", "自然语言处理")),
    (("计算机视觉", "computer vision", "cv"), ("计算机视觉", "computer vision", "cv")),
    (("数据", "data"), ("数据", "data")),
    (("后端", "backend", "back-end"), ("后端", "backend", "back-end")),
    (("前端", "frontend", "front-end"), ("前端", "frontend", "front-end")),
    (("测试", "qa"), ("测试", "quality assurance", "qa")),
    (("产品", "product"), ("产品", "product")),
)


def classify_discovery_job(job: JobStub, *, query: str | None, role_review=None) -> DiscoveryJobMatch:
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

    wanted_locations, denied_locations = select_term_groups(
        normalized_query, _LOCATION_GROUPS
    )
    if wanted_locations or denied_locations:
        locations = effective_job_locations(job)
        location_text = " ".join(locations).casefold()
        known = [
            g for g in _LOCATION_GROUPS if any(_contains(location_text, t) for t in g)
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
            uncertain = not complete or bool(
                re.search(r"优先|最好|首选", normalized_query)
            )
            record(
                "location",
                "pending" if uncertain else "excluded",
                "地点待确认" if uncertain else "地点不匹配",
                locations,
            )
        else:
            record("location", "matched", "已确认地点符合搜索条件", locations)

    type_groups = (
        ("校招", "校园招聘", "应届", "应届生"),
        ("实习", "internship", "intern"),
        ("社招", "社会招聘", "正式岗", "全职", "full-time"),
    )
    wanted_types, denied_types = select_term_groups(normalized_query, type_groups)
    type_names = dict(zip(type_groups, ("campus", "internship", "full_time")))
    if wanted_types or denied_types:
        evidence = [job.job_type] if job.job_type else []
        if job.job_type in {None, "unknown"}:
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

    positive_roles, excluded_roles = select_term_groups(
        normalized_query, [g[0] for g in _ROLE_GROUPS]
    )
    requested_roles = [
        terms for aliases, terms in _ROLE_GROUPS if aliases in positive_roles
    ]
    # Keep the application qualifier instead of expanding it to every model job.
    if re.search(r"(?:大模型|大语言模型|llm)\s*(?:应用|application)", normalized_query):
        requested_roles = [
            ("大模型应用", "大语言模型应用", "llm application", "llm应用", "rag", "检索增强", "agent", "智能体")
            if "llm" in terms or "ai应用" in terms else terms
            for terms in requested_roles
        ]
    ai_terms = ("ai", "人工智能", "artificial intelligence")
    positive_ai, excluded_ai = select_term_groups(normalized_query, [ai_terms])
    if not requested_roles and positive_ai:
        requested_roles = [ai_terms]
    from src.services.job_role_review import duty_text, valid_review

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
        if any(_contains(title, term) for term in denied_terms):
            record(
                "role",
                "excluded",
                "岗位方向在明确排除范围内",
                [job.title],
                "excluded_role",
            )
        elif accepted_review:
            decision = accepted_review["decision"]
            record("role", decision["status"], decision["reason"], decision["evidence"])
        elif requested_roles and not hits:
            record("role", "pending", "正文尚未确认目标方向", [])
        elif denied_terms and not title:
            record("role", "pending", "岗位名称缺失，排除方向待核实", [])
        else:
            record(
                "role",
                "matched",
                "岗位内容包含目标方向：" + "、".join(dict.fromkeys(hits))
                if hits
                else "岗位名称未命中排除方向",
                _source_quotes(role_text, hits)[:3] if hits else [job.title],
            )

    conditions = search_filter_conditions(query)
    years = conditions["graduation_years"]
    if years:
        # A season title or date is not an eligibility cohort. Keep the complete
        # sentence so regional qualifications and ranges cannot be dropped.
        fragments = [
            s.strip()
            for s in re.split(r"[。；;\n]", job.raw_content or "")
            if re.search(r"20\d{2}.*(?:届|毕业)|毕业.*20\d{2}", s)
        ]
        simple = [_simple_search_cohort(s) for s in fragments]
        cohorts = {int(y) for sentence in simple if sentence for y in re.findall(r"20\d{2}", sentence)}
        certain = bool(fragments) and all(simple) and len(set(simple)) == 1
        if re.search(
            r"(?:不考虑|排除|不接受).*20\d{2}|20\d{2}.*(?:至|到|[-~～]).*20\d{2}",
            normalized_query,
        ):
            certain = False
        if certain and set(years) <= cohorts:
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
                "适用届别待核实：原文缺失或含有附加条件",
                fragments,
            )
    for keyword in conditions["keywords"]:
        quotes = _source_quotes("\n".join([job.title or "", job.raw_content or ""]), [keyword])
        record(
            "keyword",
            "matched" if quotes else "pending",
            f"岗位内容包含关键词：{keyword}" if quotes else f"关键词待核实：{keyword}",
            quotes[:2],
        )
    if conditions["pending_conditions"]:
        record(
            "additional",
            "pending",
            "附加条件待核实：" + "、".join(conditions["pending_conditions"]),
            [],
        )

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
    )


def _simple_search_cohort(sentence):
    """Recognize explicit cohort facts without dropping regional/date conditions."""
    value = re.sub(r"^(?:[-•]\s*|\d+[.、]\s*)", "", sentence.strip())
    value = re.sub(r"^(?:招聘对象|招募对象|任职要求|招聘要求|毕业届别|适用届别|届别)\s*[：:]\s*", "", value)
    if classify_graduation_condition(value) == "simple":
        return ",".join(sorted(set(re.findall(r"20\d{2}", value))))
    # A header explicitly saying 届 is distinct from a year naming a campaign.
    cohort = re.fullmatch(r"(20\d{2})\s*届(?:校园招聘|校招)(?:计划|项目)?(?:\s*[-—·]\s*(?:正式批|提前批|秋招|春招))?", value)
    if cohort:
        return cohort[1]
    # A recruitment label can wrap the same explicit cohort in parentheses.
    # Match the entire label; never discard conditions inside or after it.
    cohort = re.fullmatch(
        r"(?:应届生|应届毕业生|校园招聘|校招)\s*[（(]\s*"
        r"(20\d{2})\s*届(?:应届生|应届毕业生)(?:校园招聘|校招)\s*[）)]",
        value,
    )
    if cohort:
        return cohort[1]
    if re.search(r"海外|境外|境内|国内|大陆|留学|毕业时间|毕业日期|之前|之后|如果|仅限|不接受|不招|不含|除外|或(?:符合|其他|满足)|[月日]|20\d{2}.*20\d{2}", value):
        return None
    # Some renderers flatten the education heading and its paragraph together.
    # Strip only an explicit education prefix; retain the complete sentence as
    # evidence and reject regional/date/exception qualifiers above.
    value = re.sub(r"^(?:教育背景|学历要求|教育要求|学历)\s*[:：]?\s*", "", value)
    value = re.sub(r"^(?:(?:本科|硕士|博士|研究生|大专|及以上|及|或|和|、|学历|学位|\s)+)[，,]\s*", "", value)
    cohort = re.fullmatch(r"(?:面向|招收|招聘|接受)?(20\d{2})\s*届\s*(?:本科|硕士|博士|及|或|和|、|[ /])*\s*(?:应届毕业生|应届生|毕业生)(?:[，,].*)?", value)
    return cohort[1] if cohort else None


def _source_quotes(text: str, terms: list[str]) -> list[str]:
    return list(
        dict.fromkeys(
            sentence.strip()
            for sentence in re.split(r"[。；;\n]", text)
            if any(_contains(sentence.casefold(), term.casefold()) for term in terms)
        )
    )


def search_filter_conditions(query: str | None) -> dict[str, object]:
    """Expose the local filter scope without asking users to confirm each field."""
    text = (query or "").casefold()
    locations, excluded_locations = select_term_groups(text, _LOCATION_GROUPS)
    roles, excluded_roles = select_term_groups(text, [g[0] for g in _ROLE_GROUPS])
    types, excluded_types = select_term_groups(
        text,
        (
            ("校招", "校园招聘", "应届", "应届生"),
            ("实习", "internship", "intern"),
            ("社招", "社会招聘", "正式岗", "全职", "full-time"),
        ),
    )
    year_pattern = r"(20\d{2})\s*(?:年)?\s*(?:届|校招|应届|毕业)"
    years = sorted({int(m.group(1)) for m in re.finditer(year_pattern, text)})
    pending, keywords = [], []
    aliases = sorted(
        {
            alias
            for group in (
                *_LOCATION_GROUPS,
                *(g[0] for g in _ROLE_GROUPS),
                *types,
                *excluded_types,
                ("ai", "人工智能", "artificial intelligence"),
            )
            for alias in group
        },
        key=len,
        reverse=True,
    )
    for clause in re.split(r"[，,；;。\n]", text):
        if re.search(
            r"本科|硕士|博士|学历|专业|薪资|月薪|年薪|\d+\s*[kw万千]|远程|居家|毕业时间|毕业日期|以前|以后|之前|之后|至少|以上|及以上|经验|双休|加班",
            clause,
        ):
            pending.append(clause.strip())
            continue
        rest = re.sub(year_pattern, "", clause)
        for alias in aliases:
            pattern = (
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
                if alias.isascii()
                else re.escape(alias)
            )
            rest = re.sub(pattern, " ", rest)
        rest = re.sub(
            r"应用开发|应用|研发|开发|工程师|岗位|职位|相关|方向|机会|招聘|想找|帮我|搜索|寻找|不限|接受|优先|首选|最好|只考虑|只要|仅限|不排除|不考虑|不接受|不要|排除|考虑|以及|并且|excluding|exclude|except|not\s+in|campus|[请找的和或也都]",
            " ",
            rest,
        )
        parts = re.findall(r"[a-z0-9][a-z0-9+#.-]*|[\u4e00-\u9fff]+", rest)
        if parts and re.search(r"不考虑|不接受|不要|排除|except|exclude", clause):
            pending.append(clause.strip())
        else:
            keywords.extend(parts)
    return {
        "locations": [g[0] for g in locations],
        "excluded_locations": [g[0] for g in excluded_locations],
        "roles": [g[0] for g in roles],
        "excluded_roles": [g[0] for g in excluded_roles],
        "job_types": [g[0] for g in types],
        "excluded_job_types": [g[0] for g in excluded_types],
        "graduation_years": years,
        "keywords": list(dict.fromkeys(keywords)),
        "pending_conditions": pending,
    }


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
