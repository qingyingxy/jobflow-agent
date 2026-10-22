"""Conservative classification of cohort evidence, independent of model labels."""

import re
from typing import Literal

GraduationConditionKind = Literal["simple", "qualified", "ambiguous"]

# Two-digit cohorts are supported only in the contemporary recruitment range.
# Bare two-digit numbers and historical '99届' must not acquire a century.
COHORT_YEAR_PATTERN = r"(?:20\d{2}(?:年)?(?:届)?|[2-4]\d届)"


def quoted_cohort_years(source_text: str) -> set[int]:
    """Normalize explicit year tokens without changing their quoted evidence."""
    text = re.sub(r"\s+", "", source_text)
    years = {int(m) for m in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)}
    years.update(2000 + int(m) for m in re.findall(r"(?<!\d)([2-4]\d)届", text))
    return years


def _standalone_cohort_kind(source_text: str) -> GraduationConditionKind:
    text = re.sub(r"\s+", "", source_text).strip("。.;；")
    # Only an explicit list of cohorts is safe for a year-membership check.
    year = COHORT_YEAR_PATTERN
    cohorts = rf"{year}(?:(?:、|，|,|和|或|及|/){year})*"
    if re.fullmatch(
        rf"(?:(?:本|该)(?:岗位|职位))?(?:面向|招收|招聘|接受|仅限|限)?{cohorts}"
        r"(?:应届)?(?:毕业生|毕业学生|应届生)?",
        text,
    ):
        return "simple"
    # Company names in recruitment-project headers are metadata, provided the
    # entire remaining text is a cohort + campus-recruitment label. Qualifiers
    # in that prefix must still prevent a simple membership check.
    project = re.fullmatch(
        rf"招聘项目[:：](?P<prefix>[^：:，,；;。]{{1,30}}?){cohorts}"
        r"(?:应届生|应届毕业生|毕业生)?(?:校园招聘|校招|应届生招聘)"
        r"(?:计划|项目)?(?:[-—·](?:正式批|提前批|秋招|春招))?",
        text,
    )
    explicit_cohort = bool(re.search(r"届|毕业生|毕业学生", text))
    if (
        project
        and explicit_cohort
        and not re.search(
            r"国内|大陆|境内|海外|境外|留学|面向|招收|毕业|不|非|除|限|仅|须|且|学历|本科|硕士|博士|专业|取得|获得|时间|条件|之前|之后|以前|以后|至|到|[月日]",
            project["prefix"],
        )
    ):
        return "simple"
    if (
        explicit_cohort
        and re.fullmatch(
            r"(?:(?:招聘项目|招聘对象|招聘批次|届别|毕业届别)[:：])?"
            rf"{cohorts}(?:应届生|应届毕业生|毕业生)?"
            r"(?:校园招聘|校招|应届生招聘)"
            r"(?:计划|项目)?(?:[-—·](?:正式批|提前批|秋招|春招))?",
            text,
        )
    ) or re.fullmatch(
        rf"(?:招聘对象|届别|毕业届别)[:：]{cohorts}(?:应届生|应届毕业生|毕业生)?",
        text,
    ):
        return "simple"
    if re.search(
        r"国内|大陆|境内|海外|境外|留学|毕业时间|毕业日期|取得|获得|之前|之后|以前|以后|至|到|[月日]|仅|限|且|如果",
        text,
    ):
        return "qualified"
    return "ambiguous"


def simple_cohort_years(source_text: str) -> set[int] | None:
    """Shared, bounded cohort recognition for discovery and qualification.

    Degree/major clauses remain separate predicates. Only their ordinary forms
    can accompany a cohort here; region, date windows and exceptions stay open.
    """
    value = re.sub(r"^(?:[-•]\s*|\d+[.、]\s*)", "", source_text.strip())
    value = re.sub(
        r"^(?:招聘对象|招募对象|任职要求|招聘要求|毕业届别|适用届别|届别)\s*[：:]\s*",
        "",
        value,
    )
    value = re.sub(r"\s+", "", value)
    if _standalone_cohort_kind(value) == "simple":
        return quoted_cohort_years(value)
    if re.search(
        r"海外|境外|境内|国内|大陆|留学|毕业时间|毕业日期|之前|之后|以后|以前|"
        r"如果|仅限|不接受|不招|不含|除外|以外|非|或(?:符合|其他|满足)|[月日]",
        value,
    ):
        return None
    year = COHORT_YEAR_PATTERN
    if re.search(r"届|毕业生|毕业学生", value) and (
        re.fullmatch(
            rf"{year}(?:[A-Za-z\u4e00-\u9fff]{{0,16}}人才)?(?:校园招聘|校招)"
            r"(?:计划|项目)?(?:\s*[-—·]\s*(?:正式批|提前批|秋招|春招))?",
            value,
        )
        or re.fullmatch(
            rf"(?:应届生|应届毕业生|校园招聘|校招)\s*[（(]\s*{year}"
            r"(?:应届生|应届毕业生)(?:校园招聘|校招)\s*[）)]",
            value,
        )
    ):
        return quoted_cohort_years(value)
    value = re.sub(r"^(?:教育背景|学历要求|教育要求|学历)\s*[:：]?\s*", "", value)
    degree = r"(?:大专|本科|硕士|博士|研究生)"
    degrees = rf"{degree}(?:(?:及其以上|及以上|以上|及|或|和|、|/){degree}?)*"
    major = r"(?:[\w/、\s]+专业(?:背景)?(?:的?优先)?|专业不限|不限专业)"
    degree_clause = rf"(?:获得|取得)?{degrees}(?:学历|学位)?"
    cohort_clause = (
        rf"(?:面向|招收|招聘|接受)?{year}(?:毕业)?(?:{degree_clause})?"
        r"(?:应届毕业生|应届生|毕业生)?"
    )
    parts = re.split(r"[，,]", value)
    # Ordinary education facets can appear before or after the cohort. Every
    # remaining facet must be recognized; never discard arbitrary trailing text.
    if sum(bool(re.fullmatch(cohort_clause, part)) for part in parts) == 1 and all(
        re.fullmatch(cohort_clause, part)
        or re.fullmatch(rf"(?:{degree_clause}|{major}(?:{degree_clause})?)", part)
        for part in parts
    ):
        return quoted_cohort_years(value)
    return None


def classify_graduation_condition(source_text: str) -> GraduationConditionKind:
    if simple_cohort_years(source_text) is not None:
        return "simple"
    return _standalone_cohort_kind(source_text)


def cohort_source_fragments(
    content: str, *, title: str | None = None, include_titles: bool = False
) -> list[str]:
    """Keep literal cohort quotes; a title alone cannot establish eligibility."""
    sources = []
    # Inline section headings also terminate an education clause. Keep each
    # returned fragment literal so evidence offsets and qualification facets survive.
    for fragment in re.split(r"[。；;\n]|\s+(?=必备能力\s|加分能力\s|岗位职责\s|工作职责\s)", content):
        quote = fragment.strip()
        is_title = quote == title or bool(
            re.match(r"(?:岗位名称|职位名称|招聘岗位)\s*[：:]", quote)
        )
        if is_title and not include_titles:
            continue
        if quoted_cohort_years(quote) and re.search(r"届|毕业|校园招聘|校招", quote):
            sources.append(quote)
    if (
        include_titles
        and title
        and quoted_cohort_years(title)
        and "届" in title
        and not any(
            re.sub(r"^(?:岗位名称|职位名称|招聘岗位)\s*[：:]\s*", "", quote) == title
            for quote in sources
        )
    ):
        sources.append(title)
    return list(dict.fromkeys(sources))


def cohort_conflict_sources(
    source: str,
    content: str,
    *,
    title: str | None = None,
    historical: tuple[str, ...] = (),
) -> list[str]:
    """Find conflicts/qualifiers without executing a project label as a gate."""
    years = quoted_cohort_years(source)
    conflicts = []
    for quote in cohort_source_fragments(content, title=title, include_titles=True):
        if quote == source or any(quote in old for old in historical):
            continue
        is_title = quote == title or bool(
            re.match(r"(?:岗位名称|职位名称|招聘岗位)\s*[：:]", quote)
        )
        negative = bool(
            re.search(
                r"不(?:面向|招收|招聘|接受)|不招|不含|排除|非\s*(?:20\d{2}|[2-4]\d届)|"
                r"届(?:毕业生)?(?:以外|除外)",
                quote,
            )
        )
        if quoted_cohort_years(quote) != years or (
            not is_title
            and (classify_graduation_condition(quote) == "qualified" or negative)
        ):
            conflicts.append(quote)
    return conflicts
