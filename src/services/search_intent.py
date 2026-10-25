"""Model-led request understanding with a visible, conservative local fallback.

Saved structured conditions and labelled queries remain deterministic.
"""

import re

from pydantic import ValidationError

from src.domain.search_goal import SearchGoalConditions
from src.services.search_constraints import select_term_groups, term_pattern
from src.services.search_vocabulary import _LOCATION_GROUPS, _ROLE_GROUPS

FIELD_LABELS = {
    "locations": "工作地点",
    "preferred_locations": "优先地点",
    "excluded_locations": "排除地点",
    "roles": "岗位方向",
    "preferred_roles": "优先方向",
    "excluded_roles": "排除方向",
    "job_types": "招聘类型",
    "excluded_job_types": "排除类型",
    "graduation_years": "届别",
    "keywords": "关键词",
    "preferred_keywords": "优先关键词",
    "pending_conditions": "其他要求",
}
INTENT_VERSION = "4"


_SOFT = r"优先|最好|首选|也接受|也可以|\bprefer(?:red)?\b"
_HARD = r"只考虑|只要|仅限|必须"
_SCOPE_BRIDGE = r"(?:\s|在|去|考虑|接受|选择|工作地点|地点|城市|地区|市|为|是|的|[:：])*"
_LIST_BRIDGE = r"(?:\s|[、/]|或|和|与|及|以及|或者|市|地区)*"


def role_phrases(text: str, *, keep_surface=False) -> list[str]:
    """Keep a direction's attached qualifiers, rather than reducing it to an alias.

    Boundaries are intent grammar (locations, types, lists and modifiers), not
    an enumeration of job specialisms. Unrecognised directions still go through
    the grounded semantic parser below.
    """
    aliases = sorted({a for group, _ in _ROLE_GROUPS for a in group}, key=len, reverse=True)
    matches = list(re.finditer("|".join(term_pattern(a) for a in aliases), text))
    boundary = (
        r"[\s，,；;。\n/、]|20\d{2}|校招|校园招聘|实习|社招|应届|招聘|"
        r"不限|排除|不考虑|不接受|不要|优先|首选|最好|只考虑|只要|仅限|必须|"
        r"以及|并且|或者|或|和|与|岗位|职位|方向|机会|工程师|"
        + "|".join(re.escape(a) for g in _LOCATION_GROUPS for a in g)
    )
    phrases = []
    consumed = 0
    for match in matches:
        if match.start() < consumed:
            continue
        suffix = re.split(boundary, text[match.end():], maxsplit=1)[0]
        consumed = match.end() + len(suffix)
        phrase = match.group() + suffix
        # A bare occupational suffix adds no scope. Application/platform/etc.
        # qualifiers remain literal, including unfamiliar compounds.
        if not keep_surface and suffix in {"开发", "研发", "相关"}:
            phrase = match.group()
        phrases.append(phrase)
    return list(dict.fromkeys(phrases))


def _preferred_span(text: str, start: int, end: int) -> bool:
    """Bind modifiers adjacent to a term/list, without crossing other fields."""
    before, after = text[:start], text[end:]
    # A suffix is attached to this term. A prefix must start a new phrase:
    # in "上海优先杭州", 优先 belongs to 上海, rather than to 杭州.
    prefix_boundary = r"(?:^|[\s，,；;。\n]|但|而|希望|我想|想|地点|城市)"
    hard = re.match(rf"{_SCOPE_BRIDGE}(?:{_HARD})", after) or re.search(
        rf"{prefix_boundary}(?:{_HARD}){_SCOPE_BRIDGE}$", before
    )
    soft = re.match(rf"{_SCOPE_BRIDGE}(?:{_SOFT})", after) or re.search(
        rf"{prefix_boundary}(?:{_SOFT}){_SCOPE_BRIDGE}$", before
    )
    return bool(soft and not hard)


def _preferred_groups(text: str, groups) -> set[tuple[str, ...]]:
    """A modifier can cover a named list such as 上海、杭州 or Python和Java."""
    aliases = sorted({a for group in groups for a in group}, key=len, reverse=True)
    if not aliases:
        return set()
    term = "(?:" + "|".join(term_pattern(a) for a in aliases) + ")"
    clusters = re.finditer(rf"{term}(?:{_LIST_BRIDGE}{term})*", text.casefold())
    scopes: dict[tuple[str, ...], list[bool]] = {}
    for cluster in clusters:
        soft = _preferred_span(text.casefold(), cluster.start(), cluster.end())
        for group in groups:
            if any(re.search(term_pattern(a), cluster.group()) for a in group):
                scopes.setdefault(tuple(group), []).append(soft)
    # An explicit required mention cannot be relaxed by a later preference.
    return {group for group, mentions in scopes.items() if all(mentions)}


def conditions_query(conditions: SearchGoalConditions) -> str:
    """An ordinary labelled query, reused without another model call."""
    return "；".join(
        f"{label}：{'、'.join(str(v) + ('届' if key == 'graduation_years' else '') for v in values)}"
        for key, label in FIELD_LABELS.items()
        if (values := getattr(conditions, key))
    )


def parse_conditions(query: str | None) -> SearchGoalConditions:
    text = query or ""
    # Code-owned summaries include every condition and are never reinterpreted.
    clauses = re.split(r"[；;\n]", text)
    labels = {label: key for key, label in FIELD_LABELS.items()}
    if clauses and all(
        re.match(r"^\s*(" + "|".join(labels) + r")[:：]", c) for c in clauses
    ):
        values = {}
        for clause in clauses:
            label, value = re.split(r"[:：]", clause.strip(), maxsplit=1)
            key = labels[label]
            parts = [p.strip() for p in re.split(r"[、]", value) if p.strip()]
            values[key] = (
                [int(p.removesuffix("届")) for p in parts]
                if key == "graduation_years"
                else parts
            )
        return SearchGoalConditions(**values)
    data = legacy_conditions(text)
    ai_aliases = ("ai", "人工智能", "artificial intelligence")
    positive_ai, negative_ai = select_term_groups(text, [ai_aliases])
    if positive_ai and not data["roles"]:
        data["roles"] = ["ai"]
    if negative_ai:
        data["excluded_roles"].append("ai")
    soft_roles = _preferred_groups(text, [(r,) for r in data["roles"]])
    data["preferred_roles"] = [r for r in data["roles"] if (r,) in soft_roles]
    data["roles"] = [r for r in data["roles"] if (r,) not in soft_roles]
    for clause in re.split(r"[，,；;。\n]", text):
        if re.search(
            r"(?:不考虑|排除|不接受|不要).*20\d{2}.*届|20\d{2}.*(?:至|到|[-~～]).*20\d{2}",
            clause,
        ):
            data["graduation_years"] = []
            data["pending_conditions"].append(clause.strip())
    positive, negative = select_term_groups(text, _LOCATION_GROUPS)
    soft_groups = _preferred_groups(text, _LOCATION_GROUPS)
    data.update(
        locations=[g[0] for g in positive if tuple(g) not in soft_groups],
        preferred_locations=[g[0] for g in positive if tuple(g) in soft_groups],
        excluded_locations=[g[0] for g in negative],
    )
    # These connective phrases carry no additional job requirement.
    filler = r"^(?:其他(?:城市|地点|地区)(?:也)?(?:可以|接受|考虑)|地点不限|不限地点|届别|不限届别|都可以|岗位|工作|我|我想|想|在|找|一份)$"
    data["keywords"] = [w for w in data["keywords"] if not re.fullmatch(filler, w)]
    soft_keywords = _preferred_groups(text.casefold(), [(w,) for w in data["keywords"]])
    data["preferred_keywords"] = [
        w for w in data["keywords"] if (w,) in soft_keywords
    ]
    data["keywords"] = [w for w in data["keywords"] if (w,) not in soft_keywords]
    return SearchGoalConditions(**data)


def _fallback_intent(text, *, failed=False):
    if failed:
        # An unavailable model cannot safely decide polarity, alternatives or
        # corrections. Keep the full request for editing, without guessed gates.
        conditions = SearchGoalConditions(
            pending_conditions=[text[i:i + 160] for i in range(0, len(text), 160)]
        )
        notice = "暂时未能理解这段需求，已保留原文。请重试，或点击“修改条件”填写搜索条件。"
        return conditions, {
            "pending_conditions": "原始需求（待确认）",
            "_intent_status": "needs_review",
            "_intent_notice": notice,
        }, notice
    conditions = parse_conditions(text)
    data = conditions.model_dump()
    # Uninterpreted prose is not an executable keyword requirement.
    unknown = [word for word in data["keywords"] if re.search(r"[\u4e00-\u9fff]", word)]
    data["keywords"] = [word for word in data["keywords"] if word not in unknown]
    data["pending_conditions"].extend("意图待核实：" + word for word in unknown)
    conditions = SearchGoalConditions(**data)
    notice = "部分需求尚未完成理解，已保留原文，请核对搜索条件和待确认要求。" if unknown else None
    sources = {key: "本次输入" for key, values in conditions.model_dump().items() if values}
    sources["_intent_status"] = "fallback"
    if notice:
        sources["_intent_notice"] = notice
    return conditions, sources, notice


async def interpret_intent(text, *, settings, client=None):
    """Interpret the whole request; model output never merges with rule guesses."""
    if client is None and settings.structured_model_provider in {"fake", "demo"}:
        return _fallback_intent(text)
    from src.infrastructure.llm_client import ModelClientError
    from src.services.search_intent_model import (
        IntentConflictError,
        interpret_full_intent,
    )

    try:
        return await interpret_full_intent(text, settings=settings, client=client)
    except IntentConflictError:
        raise
    except (TimeoutError, ModelClientError, ValidationError, ValueError) as error:
        conditions, sources, notice = _fallback_intent(text, failed=True)
        sources["_intent_failure"] = getattr(error, "code", type(error).__name__)
        status = getattr(error, "details", {}).get("status_code")
        if status:
            sources["_intent_http_status"] = str(status)
        return conditions, sources, notice


def repair_occupation_suffix(text, old, origins):
    """Repair only machine-added suffix gates, preserving deliberate edits."""
    if origins.get("_intent_version") == INTENT_VERSION or origins.get("keywords") != "本次输入":
        return None
    if origins.get("pending_conditions") not in (None, "本次输入（意图尚未确认）"):
        return None
    parsed = parse_conditions(text)
    if old.roles != parsed.roles or old.excluded_roles != parsed.excluded_roles:
        return None
    removed = {word for word in old.keywords if word in {"开发", "研发"} and word not in parsed.keywords}
    if not removed:
        return None
    return old.model_copy(update={
        "keywords": [word for word in old.keywords if word not in removed],
        "pending_conditions": [value for value in old.pending_conditions if value not in {f"意图待核实：{w}" for w in removed}],
    })


def legacy_conditions(query: str | None) -> dict[str, object]:
    """Expose the local filter scope without asking users to confirm each field."""
    text = (query or "").casefold()
    locations, excluded_locations = select_term_groups(text, _LOCATION_GROUPS)
    phrases = role_phrases(text)
    roles, excluded_roles = select_term_groups(text, [(p,) for p in phrases])
    types, excluded_types = select_term_groups(
        text,
        (
            ("校招", "校园招聘", "应届", "应届生"),
            ("实习", "internship", "intern"),
            ("社招", "社会招聘", "正式岗", "全职", "full-time"),
        ),
    )
    year_pattern = r"(?<!\d)(20\d{2}|\d{2})\s*(?:年)?\s*(?:届|校招|应届|毕业)"
    years = sorted({int(m[1]) + (2000 if len(m[1]) == 2 else 0) for m in re.finditer(year_pattern, text)})
    pending, keywords = [], []
    aliases = sorted(
        {
            alias
            for group in (
                *_LOCATION_GROUPS,
                *(g[0] for g in _ROLE_GROUPS),
                # Consume the whole recognized occupation even when its
                # canonical meaning omits a generic suffix such as 开发.
                *((phrase,) for phrase in role_phrases(text, keep_surface=True)),
                *roles,
                *excluded_roles,
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
        # Consume the whole modifier before stripping 不限; otherwise 地点/届别
        # becomes an accidental mandatory keyword on every returned JD.
        rest = re.sub(r"(?:工作)?(?:地点|城市|地区|届别)\s*[:：]?\s*不限|不限\s*(?:工作)?(?:地点|城市|地区|届别)", " ", rest)
        for alias in aliases:
            pattern = (
                rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])"
                if alias.isascii()
                else re.escape(alias)
            )
            rest = re.sub(pattern, " ", rest)
        rest = re.sub(
            r"工程师|岗位|职位|相关|方向|机会|招聘|想找|帮我|搜索|寻找|不限|接受|优先|首选|最好|只考虑|只要|仅限|必须|也可以|不排除|不考虑|不接受|不要|排除|考虑|以及|并且|但是|但|excluding|exclude|except|not\s+in|campus|[请找的和或也都]",
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
