from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import ValidationError

from src.domain.unified_jd import (
    TEXT_FACT_CLAUSE_FIELDS,
    FactFieldName,
    UnifiedFactEvidence,
    UnifiedJDClause,
    UnifiedJDModelOutput,
    UnifiedJobFacts,
    validate_unified_fact_clause_granularity,
    validate_unified_jd_evidence,
)
from src.domain.unified_jd_extraction import (
    UnifiedFactMentionV2,
    UnifiedJDExtractionV3,
    UnifiedSemanticClauseV2,
)

JDSectionKind = Literal[
    "metadata",
    "responsibilities",
    "requirements",
    "unknown",
]

UNIFIED_EXTRACTION_COMPILER_VERSION = "unified-jd-extraction-compiler-v7"
MODEL_FIRST_FACT_COMPILER_VERSION = "unified-jd-model-first-fact-compiler-v2"
MODEL_FIRST_NORMALIZED_FACT_COMPILER_VERSION = (
    "unified-jd-model-first-normalized-fact-compiler-v3"
)
MODEL_FIRST_V3_COMPILER_VERSION = "unified-jd-model-first-compiler-v3"
UNIFIED_EVIDENCE_LINE_EXTRACTOR_VERSION = "unified-jd-evidence-lines-v1"


@dataclass(frozen=True)
class JDTextSection:
    index: int
    kind: JDSectionKind
    source_text: str
    start_char: int
    end_char: int


@dataclass(frozen=True)
class JDEvidenceLine:
    index: int
    kind: JDSectionKind
    level_hint: Literal["preferred"] | None
    source_text: str
    start_char: int
    end_char: int
    physical_section_index: int


@dataclass(frozen=True)
class ExtractionCompilationDiagnostic:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {
            "code": self.code,
            "path": self.path,
            "message": self.message,
        }


@dataclass(frozen=True)
class CompiledUnifiedExtractionV2:
    output: UnifiedJDModelOutput
    diagnostics: tuple[ExtractionCompilationDiagnostic, ...]


@dataclass(frozen=True)
class NormalizedModelFirstFactItemV3:
    values: tuple[Any, ...]
    rule_ids: tuple[str, ...]
    error: str | None = None


@dataclass(frozen=True)
class _FactCompilationPolicy:
    allow_local_backfill: bool
    preserve_text_items: bool
    allow_source_value_fallback: bool
    allow_source_text_expansion: bool


_COMPATIBLE_FACT_POLICY = _FactCompilationPolicy(
    allow_local_backfill=True,
    preserve_text_items=False,
    allow_source_value_fallback=True,
    allow_source_text_expansion=True,
)
_MODEL_FIRST_FACT_POLICY = _FactCompilationPolicy(
    allow_local_backfill=False,
    preserve_text_items=True,
    allow_source_value_fallback=False,
    allow_source_text_expansion=False,
)
_MODEL_FIRST_NORMALIZED_FACT_POLICY = _FactCompilationPolicy(
    allow_local_backfill=False,
    preserve_text_items=False,
    allow_source_value_fallback=False,
    allow_source_text_expansion=False,
)


_HEADING_MARKERS: tuple[tuple[JDSectionKind, tuple[str, ...]], ...] = (
    (
        "unknown",
        (
            "职位简介",
            "岗位简介",
            "岗位介绍",
            "招聘职位",
        ),
    ),
    (
        "responsibilities",
        (
            "岗位职责",
            "工作职责",
            "职位职责",
            "职责描述",
            "工作内容",
            "职位描述",
            "responsibilities",
            "what you will do",
            "what you'll do",
        ),
    ),
    (
        "requirements",
        (
            "任职要求",
            "岗位要求",
            "职位要求",
            "资格要求",
            "任职资格",
            "任职条件",
            "基本要求",
            "优先条件",
            "加分项",
            "优先项",
            "requirements",
            "qualifications",
            "what you bring",
            "who you are",
        ),
    ),
    (
        "metadata",
        (
            "职位信息",
            "岗位信息",
            "基本信息",
            "招聘信息",
            "工作地点",
            "办公地点",
            "招聘类型",
        ),
    ),
)

_PREFERRED_HEADING_MARKERS = {"优先条件", "加分项", "优先项"}
_LIST_ITEM_PREFIX = re.compile(
    r"(?:^|(?<=[；;。]))\s*(?:[-*•·]\s*|"
    r"(?:\d{1,2}|[一二三四五六七八九十]+)[.、）)]\s*|"
    r"[（(]\d{1,2}[）)]\s*)"
)
_SENTENCE_BOUNDARY = re.compile(r"[；;。]+")
_REQUIREMENT_BOUNDARY = re.compile(
    r"[，,](?=\s*(?:并|且|同时|以及)?\s*"
    r"(?P<cue>使用过|具备|熟悉|掌握|能独立|有))"
)
_RESPONSIBILITY_ACTION_BOUNDARY = re.compile(
    r"[，,](?=\s*(?:并|且|同时|以及)?\s*"
    r"(?:负责|参与|设计|协同|推动|建立|开展|跟进))"
)
_EXPERIENCE_LANGUAGE = re.compile(r"经验|经历|实践|论文|发表")
_CAPABILITY_TO_SKILL_LANGUAGE = re.compile(r"(?:编程|工程|技术)?基础扎实\s*$")
_LEGACY_EXPERIENCE_TYPE_ALIASES = {
    "项目经验": "project",
    "使用过": "practical",
    "实践": "practical",
    "product_usage": "practical",
    "tool_usage": "practical",
    "practice": "practical",
}

_BULLET_PREFIX = re.compile(
    r"^(?:\s*(?:[-*•·]|(?:\d{1,2}|[一二三四五六七八九十]+)[.、）)]|"
    r"[（(]\d{1,2}[）)]))\s*"
)
_PREFERRED_MARKERS = re.compile(r"优先|加分|更佳|preferred", re.IGNORECASE)
_EXPLICIT_REQUIRED_MARKERS = re.compile(
    r"必须|仅限|只限|要求|需(?:要|具备|满足)?|required",
    re.IGNORECASE,
)
_OR_MARKERS = re.compile(r"至少(?:一|1)种|任一|任选|或者|或|/|\bor\b", re.IGNORECASE)
_OPEN_GROUP_MARKERS = re.compile(r"包括但不限于|不限于|以及其他|相关专业|等")

_JOB_TYPE_ALIASES = {
    "campus": "campus",
    "校园招聘": "campus",
    "校招": "campus",
    "应届生": "campus",
    "应届": "campus",
    "internship": "internship",
    "intern": "internship",
    "实习生": "internship",
    "实习": "internship",
    "fulltime": "full_time",
    "full_time": "full_time",
    "全职": "full_time",
    "正式员工": "full_time",
    "parttime": "part_time",
    "part_time": "part_time",
    "兼职": "part_time",
}
_CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}
_LIST_FACT_FIELDS = {
    "locations",
    "graduation_years",
    "education_requirements",
    "major_requirements",
}
_SCALAR_FACT_FIELDS = {
    "job_type",
    "internship_duration_months",
    "weekly_days",
    "earliest_start_date",
    "deadline",
}
_FACT_GROUP_NAMES: dict[FactFieldName, str] = {
    "job_type": "岗位类型",
    "locations": "工作地点",
    "graduation_years": "毕业届别",
    "education_requirements": "学历范围",
    "major_requirements": "专业范围",
    "internship_duration_months": "实习时长",
    "weekly_days": "每周到岗天数",
    "earliest_start_date": "最早到岗日期",
    "deadline": "申请截止日期",
}


def split_unified_jd_sections(source_content: str) -> tuple[JDTextSection, ...]:
    """Split exact source spans and attach only a local structural hint."""

    raw_units: list[tuple[int, int]] = []
    for match in re.finditer(r"[^\r\n]+", source_content):
        start, end = match.span()
        while start < end and source_content[start].isspace():
            start += 1
        while end > start and source_content[end - 1].isspace():
            end -= 1
        if start < end:
            raw_units.append((start, end))

    if not raw_units and source_content:
        raw_units.append((0, len(source_content)))

    sections: list[JDTextSection] = []
    current_kind: JDSectionKind = "unknown"
    for start, end in raw_units:
        text = source_content[start:end]
        detected = _section_kind(text)
        if detected is not None:
            current_kind = detected
        elif current_kind == "unknown" and _looks_like_metadata(text):
            current_kind = "metadata"
        sections.append(
            JDTextSection(
                index=len(sections),
                kind=current_kind,
                source_text=text,
                start_char=start,
                end_char=end,
            )
        )
    return tuple(sections)


def extract_unified_jd_evidence_lines(
    source_content: str,
) -> tuple[JDEvidenceLine, ...]:
    """Build exact-offset evidence units before semantic classification."""

    lines: list[JDEvidenceLine] = []
    current_kind: JDSectionKind = "unknown"
    level_hint: Literal["preferred"] | None = None
    for physical in split_unified_jd_sections(source_content):
        if current_kind == "unknown" and physical.kind == "metadata":
            current_kind = "metadata"
        cursor = physical.start_char
        for start, end, kind, marker in _heading_events(
            physical.source_text,
            physical.start_char,
        ):
            _append_evidence_region(
                lines,
                source_content,
                cursor,
                start,
                current_kind,
                level_hint,
                physical.index,
            )
            current_kind = kind
            level_hint = "preferred" if marker in _PREFERRED_HEADING_MARKERS else None
            cursor = end
            while cursor < physical.end_char and source_content[cursor].isspace():
                cursor += 1
            if cursor < physical.end_char and source_content[cursor] in ":：":
                cursor += 1
        _append_evidence_region(
            lines,
            source_content,
            cursor,
            physical.end_char,
            current_kind,
            level_hint,
            physical.index,
        )
    return tuple(
        JDEvidenceLine(
            index=index,
            kind=line.kind,
            level_hint=line.level_hint,
            source_text=line.source_text,
            start_char=line.start_char,
            end_char=line.end_char,
            physical_section_index=line.physical_section_index,
        )
        for index, line in enumerate(lines)
    )


def _heading_events(
    text: str,
    absolute_start: int,
) -> list[tuple[int, int, JDSectionKind, str]]:
    candidates: list[tuple[int, int, JDSectionKind, str]] = []
    for kind, markers in _HEADING_MARKERS:
        if kind == "metadata":
            continue
        for marker in markers:
            for match in re.finditer(re.escape(marker), text, flags=re.IGNORECASE):
                tail = text[match.end() :]
                if not (re.match(r"\s*[:：]", tail) or not tail.strip()):
                    continue
                candidates.append(
                    (
                        absolute_start + match.start(),
                        absolute_start + match.end(),
                        kind,
                        marker,
                    )
                )
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    events: list[tuple[int, int, JDSectionKind, str]] = []
    occupied_until = -1
    for candidate in candidates:
        if candidate[0] < occupied_until:
            continue
        events.append(candidate)
        occupied_until = candidate[1]
    return events


def _append_evidence_region(
    lines: list[JDEvidenceLine],
    source_content: str,
    start: int,
    end: int,
    kind: JDSectionKind,
    level_hint: Literal["preferred"] | None,
    physical_section_index: int,
) -> None:
    if _is_structural_heading_span(source_content, start, end):
        return
    start, end = _trim_span(source_content, start, end)
    if start >= end:
        return
    item_boundaries = [
        start + match.start()
        for match in _LIST_ITEM_PREFIX.finditer(source_content[start:end])
    ]
    if not item_boundaries or item_boundaries[0] != start:
        item_boundaries.insert(0, start)
    item_boundaries.append(end)
    for position in range(len(item_boundaries) - 1):
        item_start = item_boundaries[position]
        item_end = item_boundaries[position + 1]
        prefix = _LIST_ITEM_PREFIX.match(source_content[item_start:item_end])
        if prefix is not None:
            item_start += prefix.end()
        for sentence_start, sentence_end in _split_span(
            source_content,
            item_start,
            item_end,
            _SENTENCE_BOUNDARY,
        ):
            if _is_structural_heading_span(
                source_content,
                sentence_start,
                sentence_end,
            ):
                continue
            for unit_start, unit_end in _split_semantic_span(
                source_content,
                sentence_start,
                sentence_end,
                kind,
            ):
                unit_start, unit_end = _trim_span(
                    source_content,
                    unit_start,
                    unit_end,
                )
                if unit_start >= unit_end:
                    continue
                lines.append(
                    JDEvidenceLine(
                        index=len(lines),
                        kind=kind,
                        level_hint=level_hint,
                        source_text=source_content[unit_start:unit_end],
                        start_char=unit_start,
                        end_char=unit_end,
                        physical_section_index=physical_section_index,
                    )
                )


def _split_semantic_span(
    source_content: str,
    start: int,
    end: int,
    kind: JDSectionKind,
) -> list[tuple[int, int]]:
    if kind == "requirements":
        boundaries: list[int] = []
        cursor = start
        for match in _REQUIREMENT_BOUNDARY.finditer(source_content[start:end]):
            boundary = start + match.start()
            preceding_text = source_content[cursor:boundary].strip()
            cue = match.group("cue")
            should_split = (
                cue in {"有", "使用过", "掌握", "能独立"}
                or (cue == "具备" and bool(_EXPERIENCE_LANGUAGE.search(preceding_text)))
                or (
                    cue == "熟悉"
                    and bool(_CAPABILITY_TO_SKILL_LANGUAGE.search(preceding_text))
                )
            )
            if should_split:
                boundaries.append(boundary)
                cursor = start + match.end()
        return _split_at_offsets(start, end, boundaries)

    if kind == "responsibilities":
        boundaries = [
            start + match.start()
            for match in _RESPONSIBILITY_ACTION_BOUNDARY.finditer(
                source_content[start:end]
            )
        ]
        if len(boundaries) >= 2:
            return _split_at_offsets(start, end, boundaries)
    return [(start, end)]


def _split_at_offsets(
    start: int,
    end: int,
    boundaries: list[int],
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    for boundary in boundaries:
        result.append((cursor, boundary))
        cursor = boundary + 1
    result.append((cursor, end))
    return result


def _split_span(
    source_content: str,
    start: int,
    end: int,
    boundary: re.Pattern[str],
) -> list[tuple[int, int]]:
    result: list[tuple[int, int]] = []
    cursor = start
    for match in boundary.finditer(source_content[start:end]):
        boundary_start = start + match.start()
        boundary_end = start + match.end()
        result.append((cursor, boundary_start))
        cursor = boundary_end
    result.append((cursor, end))
    return result


def _trim_span(source_content: str, start: int, end: int) -> tuple[int, int]:
    while start < end and source_content[start].isspace():
        start += 1
    while end > start and (
        source_content[end - 1].isspace() or source_content[end - 1] in ":："
    ):
        end -= 1
    return start, end


def _is_structural_heading_span(
    source_content: str,
    start: int,
    end: int,
) -> bool:
    text = source_content[start:end].strip()
    if not text:
        return True
    folded = _BULLET_PREFIX.sub("", text).strip().rstrip(":：").casefold()
    if any(
        folded == marker.casefold()
        for _, markers in _HEADING_MARKERS
        for marker in markers
    ):
        return True
    return len(folded) <= 40 and text.endswith((":", "："))


def compile_unified_extraction_v2(
    raw_output: dict[str, Any],
    source_content: str,
) -> CompiledUnifiedExtractionV2:
    """Compile valid extraction elements while isolating item-level failures."""

    return _compile_unified_extraction(
        raw_output,
        source_content,
        fact_policy=_COMPATIBLE_FACT_POLICY,
    )


def compile_model_first_extraction_v2(
    raw_output: dict[str, Any],
    source_content: str,
) -> CompiledUnifiedExtractionV2:
    """Compile only model-owned fact values without local expansion or backfill."""

    return _compile_unified_extraction(
        raw_output,
        source_content,
        fact_policy=_MODEL_FIRST_FACT_POLICY,
    )


def compile_model_first_normalized_extraction_v3(
    raw_output: dict[str, Any],
    source_content: str,
) -> CompiledUnifiedExtractionV2:
    """Normalize model-owned values without source expansion or local backfill."""

    return _compile_unified_extraction(
        raw_output,
        source_content,
        fact_policy=_MODEL_FIRST_NORMALIZED_FACT_POLICY,
    )


def compile_model_first_extraction_v3(
    raw_output: dict[str, Any],
    source_content: str,
) -> CompiledUnifiedExtractionV2:
    """Validate paired surface items, then compile their semantic values."""

    extraction = UnifiedJDExtractionV3.model_validate(raw_output)
    source_texts = [item.source_text for item in extraction.fact_mentions]
    source_texts.extend(item.source_text for item in extraction.clauses)
    if any(source_text not in source_content for source_text in source_texts):
        raise ValueError("V3 source_text 必须是岗位正文的精确子串")
    legacy_output = {
        "fact_mentions": [
            {
                "field": mention.field,
                "raw_items": [item.raw_item for item in mention.items],
                "level": mention.level,
                "source_text": mention.source_text,
            }
            for mention in extraction.fact_mentions
        ],
        "clauses": [
            {
                "category": clause.category,
                "level": clause.level,
                "relation": clause.relation,
                "items": [item.semantic_item for item in clause.items],
                "examples": [item.semantic_item for item in clause.examples]
                if clause.examples
                else None,
                "group_name": clause.group_name,
                "allow_other": clause.allow_other,
                "qualifier": clause.qualifier.model_dump(mode="json")
                if clause.qualifier
                else None,
                "source_text": clause.source_text,
            }
            for clause in extraction.clauses
        ],
    }
    return compile_unified_extraction_v2(legacy_output, source_content)


def normalize_model_first_fact_item_v3(
    field: FactFieldName,
    raw_item: str,
) -> NormalizedModelFirstFactItemV3:
    """Normalize one model-owned fact item and expose the applied rule."""

    mention = UnifiedFactMentionV2(
        field=field,
        raw_items=[raw_item],
        level=None,
        source_text=raw_item,
    )
    try:
        values = _convert_fact_mention(
            mention,
            policy=_MODEL_FIRST_NORMALIZED_FACT_POLICY,
        )
    except ValueError as error:
        return NormalizedModelFirstFactItemV3(
            values=(),
            rule_ids=(),
            error=str(error),
        )
    return NormalizedModelFirstFactItemV3(
        values=tuple(values),
        rule_ids=(_fact_normalization_rule_id(field, raw_item, values),),
    )


def _compile_unified_extraction(
    raw_output: dict[str, Any],
    source_content: str,
    *,
    fact_policy: _FactCompilationPolicy,
) -> CompiledUnifiedExtractionV2:

    fact_items, clause_items = _validate_envelope(raw_output)
    diagnostics: list[ExtractionCompilationDiagnostic] = []
    mentions: list[tuple[int, UnifiedFactMentionV2]] = []
    semantic_clauses: list[tuple[int, UnifiedSemanticClauseV2]] = []

    for index, item in enumerate(fact_items):
        normalized_item, recovery = _recover_fact_mention_shape(item)
        if recovery is not None:
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="recovered_fact_item_text",
                    path=f"fact_mentions[{index}].raw_items",
                    message=recovery,
                )
            )
        try:
            mention = UnifiedFactMentionV2.model_validate(normalized_item)
        except ValidationError as error:
            diagnostics.append(
                _validation_diagnostic(
                    "invalid_fact_mention", f"fact_mentions[{index}]", error
                )
            )
            continue
        if mention.source_text not in source_content:
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="unsupported_evidence",
                    path=f"fact_mentions[{index}].source_text",
                    message="事实证据无法在岗位正文中精确定位",
                )
            )
            continue
        mentions.append((index, mention))

    for index, item in enumerate(clause_items):
        normalized_item, recovery = _recover_clause_shape(item)
        if recovery is not None:
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="recovered_clause_shape",
                    path=f"clauses[{index}]",
                    message=recovery,
                )
            )
        try:
            clause = UnifiedSemanticClauseV2.model_validate(normalized_item)
        except ValidationError as error:
            diagnostics.append(
                _validation_diagnostic("invalid_clause", f"clauses[{index}]", error)
            )
            continue
        if clause.source_text not in source_content:
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="unsupported_evidence",
                    path=f"clauses[{index}].source_text",
                    message="clause 证据无法在岗位正文中精确定位",
                )
            )
            continue
        semantic_clauses.append((index, clause))

    if fact_policy.allow_local_backfill:
        existing_fact_fields = {mention.field for _, mention in mentions}
        for mention in _locally_backfilled_fact_mentions(
            source_content,
            existing_fact_fields,
        ):
            mentions.append((len(fact_items) + len(mentions), mention))
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="locally_backfilled_fact",
                    path=f"facts.{mention.field}",
                    message=f"从本地可解析的原文补全 {mention.field}",
                )
            )

    facts_payload: dict[str, Any] = {
        field_name: None
        for field_name in (*sorted(_LIST_FACT_FIELDS), *sorted(_SCALAR_FACT_FIELDS))
    }
    evidences: list[UnifiedFactEvidence] = []
    fact_clauses: list[UnifiedJDClause] = []
    seen_evidence: set[tuple[str, str]] = set()

    for index, mention in mentions:
        try:
            converted = _convert_fact_mention(mention, policy=fact_policy)
        except ValueError as error:
            diagnostics.append(
                ExtractionCompilationDiagnostic(
                    code="unsupported_fact_value",
                    path=f"fact_mentions[{index}].raw_items",
                    message=str(error),
                )
            )
            continue

        field_name = mention.field
        if field_name in _LIST_FACT_FIELDS:
            previous = facts_payload[field_name] or []
            facts_payload[field_name] = _unique([*previous, *converted])
        else:
            value = converted[0]
            previous = facts_payload[field_name]
            if previous is not None and previous != value:
                diagnostics.append(
                    ExtractionCompilationDiagnostic(
                        code="conflicting_fact_value",
                        path=f"fact_mentions[{index}]",
                        message=f"{field_name} 与更早的事实值冲突，已保留首次值",
                    )
                )
                continue
            facts_payload[field_name] = value

        evidence_key = (field_name, mention.source_text)
        if evidence_key not in seen_evidence:
            evidences.append(
                UnifiedFactEvidence(field=field_name, source_text=mention.source_text)
            )
            seen_evidence.add(evidence_key)

        clause_level = _fact_clause_level(mention, source_content)
        if clause_level is None:
            if mention.level in {"required", "preferred"}:
                diagnostics.append(
                    ExtractionCompilationDiagnostic(
                        code="implicit_metadata_level_dropped",
                        path=f"fact_mentions[{index}].level",
                        message=(
                            f"{field_name} 的证据没有显式强度，未生成 fact clause"
                        ),
                    )
                )
            continue
        clause_items = _fact_clause_items(mention, converted)
        has_alternative_marker = bool(_OR_MARKERS.search(mention.source_text))
        if mention.field == "major_requirements":
            has_alternative_marker = has_alternative_marker or bool(
                _OPEN_GROUP_MARKERS.search(mention.source_text)
            )
        relation = (
            "any_of" if len(clause_items) >= 2 and has_alternative_marker else "all_of"
        )
        fact_clauses.append(
            UnifiedJDClause(
                category="fact",
                fact_field=field_name,
                level=clause_level,
                relation=relation,
                items=clause_items,
                group_name=_FACT_GROUP_NAMES[field_name]
                if relation == "any_of"
                else None,
                allow_other=bool(
                    relation == "any_of"
                    and _OPEN_GROUP_MARKERS.search(mention.source_text)
                ),
                source_text=mention.source_text,
            )
        )

    facts_payload["evidence"] = evidences
    facts = UnifiedJobFacts.model_validate(facts_payload)
    fact_clauses = _retain_aligned_text_fact_clauses(
        facts,
        fact_clauses,
        diagnostics,
    )

    clauses = list(fact_clauses)
    for _, clause in semantic_clauses:
        clauses.append(
            UnifiedJDClause(
                category=clause.category,
                level="mention"
                if clause.category == "responsibility"
                else clause.level,
                relation=clause.relation,
                items=clause.items,
                examples=clause.examples,
                group_name=clause.group_name,
                allow_other=clause.allow_other,
                qualifier=clause.qualifier,
                source_text=clause.source_text,
            )
        )

    _append_evidence_line_coverage_diagnostics(
        source_content,
        [mention for _, mention in mentions],
        [clause for _, clause in semantic_clauses],
        diagnostics,
    )

    output = UnifiedJDModelOutput(facts=facts, clauses=clauses)
    validate_unified_fact_clause_granularity(output)
    validate_unified_jd_evidence(output, source_content)
    return CompiledUnifiedExtractionV2(output, tuple(diagnostics))


def _validate_envelope(raw_output: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    if not isinstance(raw_output, dict):
        raise TypeError("抽取结果顶层必须是对象")
    missing = {"fact_mentions", "clauses"} - raw_output.keys()
    if missing:
        raise ValueError("抽取结果缺少顶层字段：" + ", ".join(sorted(missing)))
    fact_items = raw_output["fact_mentions"]
    clause_items = raw_output["clauses"]
    if not isinstance(fact_items, list) or not isinstance(clause_items, list):
        raise TypeError("fact_mentions 和 clauses 必须都是数组")
    return fact_items, clause_items


def _recover_clause_shape(item: Any) -> tuple[Any, str | None]:
    if not isinstance(item, dict):
        return item, None
    result = dict(item)
    recoveries: list[str] = []
    legacy_all_of = result.pop("all_of", None)
    legacy_any_of = result.pop("any_of", None)
    if isinstance(legacy_any_of, list) and len(legacy_any_of) >= 2:
        result["relation"] = "any_of"
        result["items"] = legacy_any_of
        if not result.get("group_name"):
            result["group_name"] = "候选项"
        recoveries.append("旧式 any_of 数组已转换为 relation + items")
    elif legacy_any_of is True:
        result["relation"] = "any_of"
        recoveries.append("布尔 any_of 已转换为 relation=any_of")
    elif legacy_all_of is True:
        result["relation"] = "all_of"
        recoveries.append("布尔 all_of 已转换为 relation=all_of")

    qualifier = result.get("qualifier")
    if (
        result.get("category") == "experience"
        and isinstance(qualifier, str)
        and qualifier in _LEGACY_EXPERIENCE_TYPE_ALIASES
    ):
        result["qualifier"] = {
            "experience_type": _LEGACY_EXPERIENCE_TYPE_ALIASES[qualifier]
        }
        recoveries.append("字符串 qualifier 已转换为 experience_type 对象")
    elif result.get("category") == "experience" and isinstance(qualifier, str):
        result["qualifier"] = None
        recoveries.append("无法无歧义结构化的字符串 qualifier 已舍弃")
    elif (
        result.get("category") == "experience"
        and isinstance(qualifier, dict)
        and qualifier.get("experience_type") in _LEGACY_EXPERIENCE_TYPE_ALIASES
    ):
        result["qualifier"] = {
            **qualifier,
            "experience_type": _LEGACY_EXPERIENCE_TYPE_ALIASES[
                qualifier["experience_type"]
            ],
        }
        recoveries.append("experience_type 别名已转换为契约枚举")

    relation = result.get("relation", "all_of")
    items = result.get("items")
    if isinstance(items, list) and all(isinstance(value, str) for value in items):
        normalized_items = _unique(items)
        if normalized_items != items:
            result["items"] = normalized_items
            items = normalized_items
            recoveries.append("重复 clause items 已去重")
    if relation == "any_of" and isinstance(items, list) and len(items) < 2:
        result["relation"] = "all_of"
        result["group_name"] = None
        result["allow_other"] = False
        relation = "all_of"
        recoveries.append("单项 any_of 已降级为 all_of")
    if relation == "any_of" and not result.get("group_name"):
        group_names = {
            "skill": "技能选项",
            "capability": "能力选项",
            "experience": "经历选项",
            "responsibility": "职责选项",
        }
        result["group_name"] = group_names.get(result.get("category"), "候选项")
        recoveries.append("any_of 缺失的 group_name 已按 category 补全")
    if relation == "all_of" and (
        result.get("group_name") is not None or result.get("allow_other") is True
    ):
        result["group_name"] = None
        result["allow_other"] = False
        recoveries.append("all_of 的组字段已清空")
    return result, "；".join(recoveries) if recoveries else None


def _recover_fact_mention_shape(item: Any) -> tuple[Any, str | None]:
    if not isinstance(item, dict):
        return item, None
    result = dict(item)
    raw_items = result.get("raw_items")
    if isinstance(raw_items, (str, int)) and not isinstance(raw_items, bool):
        result["raw_items"] = [str(raw_items)]
        return result, "单个事实值已包装为字符串数组"
    if not isinstance(raw_items, list):
        return result, None
    normalized = [
        str(value) if isinstance(value, int) and not isinstance(value, bool) else value
        for value in raw_items
    ]
    if normalized != raw_items:
        result["raw_items"] = normalized
        return result, "数字事实值已转换为字符串"
    return result, None


def _validation_diagnostic(
    code: str,
    path: str,
    error: ValidationError,
) -> ExtractionCompilationDiagnostic:
    first = error.errors()[0]
    location = ".".join(str(part) for part in first["loc"])
    suffix = f".{location}" if location else ""
    return ExtractionCompilationDiagnostic(
        code=code,
        path=f"{path}{suffix}",
        message=first["msg"],
    )


def _convert_fact_mention(
    mention: UnifiedFactMentionV2,
    *,
    policy: _FactCompilationPolicy,
) -> list[Any]:
    field_name = mention.field
    if field_name == "locations":
        return [_normalize_location(item) for item in mention.raw_items]
    if field_name == "education_requirements":
        if policy.preserve_text_items:
            return list(mention.raw_items)
        return _normalize_education_items(
            mention,
            allow_source_expansion=policy.allow_source_text_expansion,
        )
    if field_name == "major_requirements":
        if policy.preserve_text_items:
            return list(mention.raw_items)
        return _normalize_major_items(
            mention,
            allow_source_expansion=policy.allow_source_text_expansion,
        )
    if field_name == "graduation_years":
        years: list[int] = []
        for item in mention.raw_items:
            years.extend(
                int(value)
                for value in re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", item)
            )
        if not years and policy.allow_source_value_fallback:
            years.extend(
                int(value)
                for value in re.findall(
                    r"(?<!\d)(?:19|20|21)\d{2}(?!\d)",
                    mention.source_text,
                )
            )
        years = _unique(years)
        if not years:
            raise ValueError("graduation_years 中没有可解析的四位年份")
        return years
    if field_name == "job_type":
        candidates = list(mention.raw_items)
        if policy.allow_source_value_fallback:
            candidates.append(mention.source_text)
        for item in candidates:
            normalized = re.sub(r"[\s-]+", "", item).casefold()
            for alias, job_type in _JOB_TYPE_ALIASES.items():
                if alias.casefold() in normalized:
                    return [job_type]
        raise ValueError("job_type 中没有可识别的岗位类型")
    if field_name == "internship_duration_months":
        values = list(mention.raw_items)
        if policy.allow_source_value_fallback:
            values.append(mention.source_text)
        value = _duration_months(values)
        if value is None:
            raise ValueError("internship_duration_months 中没有可解析的月数")
        return [value]
    if field_name == "weekly_days":
        values = list(mention.raw_items)
        if policy.allow_source_value_fallback:
            values.append(mention.source_text)
        value = _weekly_days(values)
        if value is None or not 1 <= value <= 7:
            raise ValueError("weekly_days 中没有 1 到 7 的可解析天数")
        return [value]
    if field_name in {"earliest_start_date", "deadline"}:
        values = list(mention.raw_items)
        if policy.allow_source_value_fallback:
            values.append(mention.source_text)
        value = _full_date(values)
        if value is None:
            raise ValueError(f"{field_name} 中没有可解析的完整日期")
        return [value]
    raise ValueError(f"不支持的事实字段：{field_name}")


def _fact_normalization_rule_id(
    field: FactFieldName,
    raw_item: str,
    values: list[Any],
) -> str:
    if len(values) == 1 and values[0] == raw_item:
        return "fact.normalize.identity"
    return {
        "locations": "fact.normalize.location-city-suffix",
        "graduation_years": "fact.normalize.graduation-year-integer",
        "education_requirements": "fact.normalize.education-identity",
        "major_requirements": "fact.normalize.major-atomization",
        "job_type": "fact.normalize.job-type-alias",
        "internship_duration_months": "fact.normalize.duration-months-integer",
        "weekly_days": "fact.normalize.weekly-days-integer",
        "earliest_start_date": "fact.normalize.iso-date",
        "deadline": "fact.normalize.iso-date",
    }[field]


def _normalize_location(value: str) -> str:
    normalized = value.strip()
    if re.fullmatch(r"[\u4e00-\u9fff]{2,8}市", normalized):
        return normalized[:-1]
    return normalized


def _normalize_education_items(
    mention: UnifiedFactMentionV2,
    *,
    allow_source_expansion: bool,
) -> list[str]:
    if not allow_source_expansion:
        return list(mention.raw_items)
    institution_phrase = re.search(
        r"((?:国内外)?(?:著名|知名|重点|一流)?(?:高校|院校)"
        r"[^，,；;。]{0,40}(?:学历|学位))",
        _BULLET_PREFIX.sub("", mention.source_text).strip(),
    )
    if institution_phrase and any(
        item in institution_phrase.group(1) for item in mention.raw_items
    ):
        return [institution_phrase.group(1)]
    return list(mention.raw_items)


def _normalize_major_items(
    mention: UnifiedFactMentionV2,
    *,
    allow_source_expansion: bool,
) -> list[str]:
    result: list[str] = []
    for raw_item in mention.raw_items:
        expanded = re.sub(r"等\s*相关专业", "、相关专业", raw_item)
        result.extend(
            part.strip()
            for part in re.split(r"\s*(?:、|,|，|/|或者|或)\s*", expanded)
            if part.strip()
        )
    if (
        allow_source_expansion
        and "相关专业" in mention.source_text
        and not any(item == "相关专业" for item in result)
    ):
        result.append("相关专业")
    return _unique(result)


def _fact_clause_items(
    mention: UnifiedFactMentionV2,
    converted: list[Any],
) -> list[str]:
    if mention.field in TEXT_FACT_CLAUSE_FIELDS:
        return [str(item) for item in converted]
    if mention.field != "graduation_years":
        return _unique(list(mention.raw_items))
    result: list[str] = []
    for year in converted:
        raw_item = next(
            (
                item
                for item in mention.raw_items
                if item in mention.source_text
                and re.findall(r"(?<!\d)(?:19|20|21)\d{2}(?!\d)", item) == [str(year)]
            ),
            None,
        )
        if raw_item is not None and raw_item != str(year):
            result.append(raw_item)
            continue
        match = re.search(rf"(?<!\d){year}\s*(?:届|年)(?!\d)", mention.source_text)
        result.append(match.group(0) if match else str(year))
    return result


def _duration_months(values: list[str]) -> int | None:
    for value in values:
        if "半年" in value:
            return 6
        year_match = re.search(r"([1-9]\d*|[一二两三四五六七八九十]+)\s*年", value)
        if year_match:
            number = _positive_int(year_match.group(1))
            if number is not None:
                return number * 12
        month_match = re.search(
            r"([1-9]\d*|[一二两三四五六七八九十]+)\s*(?:个)?月",
            value,
        )
        if month_match:
            number = _positive_int(month_match.group(1))
            if number is not None:
                return number
        if value.strip().isdigit() and int(value.strip()) > 0:
            return int(value.strip())
    return None


def _weekly_days(values: list[str]) -> int | None:
    for value in values:
        match = re.search(
            r"(?:每周|周)\D{0,4}([1-7]|[一二两三四五六七])\s*(?:天|日)?",
            value,
        )
        if match:
            return _positive_int(match.group(1))
        if value.strip() in {"1", "2", "3", "4", "5", "6", "7"}:
            return int(value.strip())
    return None


def _full_date(values: list[str]) -> date | None:
    for value in values:
        iso_match = re.search(r"((?:19|20|21)\d{2})-(\d{1,2})-(\d{1,2})", value)
        cn_match = re.search(
            r"((?:19|20|21)\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?",
            value,
        )
        match = iso_match or cn_match
        if match:
            try:
                return date(*(int(part) for part in match.groups()))
            except ValueError:
                continue
    return None


def _positive_int(value: str) -> int | None:
    if value.isdigit():
        result = int(value)
        return result if result > 0 else None
    return _CHINESE_NUMBERS.get(value)


def _fact_clause_level(
    mention: UnifiedFactMentionV2,
    source_content: str,
) -> str | None:
    if mention.level not in {"required", "preferred"}:
        if mention.field == "major_requirements" and _PREFERRED_MARKERS.search(
            mention.source_text
        ):
            return "preferred"
        if (
            mention.field not in {"job_type", "locations"}
            and _source_section_kind(source_content, mention.source_text)
            == "requirements"
        ):
            return "required"
        return None
    if mention.level == "preferred" and _PREFERRED_MARKERS.search(mention.source_text):
        return "preferred"
    if mention.field not in {"job_type", "locations"}:
        return mention.level
    if mention.level == "required" and _EXPLICIT_REQUIRED_MARKERS.search(
        mention.source_text
    ):
        return "required"
    return None


def _source_section_kind(
    source_content: str,
    source_text: str,
) -> JDSectionKind:
    start = source_content.find(source_text)
    if start < 0:
        return "unknown"
    for section in split_unified_jd_sections(source_content):
        if section.start_char <= start < section.end_char:
            return section.kind
    return "unknown"


def _locally_backfilled_fact_mentions(
    source_content: str,
    existing_fields: set[FactFieldName],
) -> list[UnifiedFactMentionV2]:
    if "graduation_years" in existing_fields:
        return []
    mentions: list[UnifiedFactMentionV2] = []
    seen_years: set[int] = set()
    for section in split_unified_jd_sections(source_content):
        years = [
            int(value)
            for value in re.findall(
                r"(?<!\d)((?:19|20|21)\d{2})\s*届",
                section.source_text,
            )
        ]
        if (
            not years
            and re.match(r"^(?:招聘项目|招聘批次)\s*[:：]", section.source_text)
            and re.search(r"校园招聘|校招|应届", section.source_text)
        ):
            years = [
                int(value)
                for value in re.findall(
                    r"(?<!\d)((?:19|20|21)\d{2})(?!\d)",
                    section.source_text,
                )
            ]
        new_years = [year for year in years if year not in seen_years]
        if not new_years:
            continue
        seen_years.update(new_years)
        source_text = section.source_text
        if len(source_text) > 240:
            source_text = f"{new_years[0]}届"
        mentions.append(
            UnifiedFactMentionV2(
                field="graduation_years",
                raw_items=[f"{year}届" for year in new_years],
                level=None,
                source_text=source_text,
            )
        )
    return mentions


def _retain_aligned_text_fact_clauses(
    facts: UnifiedJobFacts,
    clauses: list[UnifiedJDClause],
    diagnostics: list[ExtractionCompilationDiagnostic],
) -> list[UnifiedJDClause]:
    retained = list(clauses)
    for field_name in TEXT_FACT_CLAUSE_FIELDS:
        matching = [item for item in retained if item.fact_field == field_name]
        if not matching:
            continue
        fact_values = getattr(facts, field_name)
        clause_values = _unique([item for clause in matching for item in clause.items])
        if fact_values is not None and set(fact_values) == set(clause_values):
            continue
        retained = [item for item in retained if item.fact_field != field_name]
        diagnostics.append(
            ExtractionCompilationDiagnostic(
                code="unaligned_fact_clauses_dropped",
                path=f"facts.{field_name}",
                message="事实值与带强度的 mentions 不完全一致，已保留事实并舍弃该字段 clauses",
            )
        )
    return retained


def _append_evidence_line_coverage_diagnostics(
    source_content: str,
    mentions: list[UnifiedFactMentionV2],
    clauses: list[UnifiedSemanticClauseV2],
    diagnostics: list[ExtractionCompilationDiagnostic],
) -> None:
    responsibility_clauses = [
        clause for clause in clauses if clause.category == "responsibility"
    ]
    requirement_sources = [mention.source_text for mention in mentions]
    requirement_sources.extend(
        clause.source_text for clause in clauses if clause.category != "responsibility"
    )
    for line in extract_unified_jd_evidence_lines(source_content):
        if line.kind == "responsibilities":
            candidate_sources = [
                clause.source_text for clause in responsibility_clauses
            ]
            code = "uncovered_responsibility_evidence_line"
            message = "职责 evidence line 没有对应的有效 responsibility clause"
        elif line.kind == "requirements":
            candidate_sources = requirement_sources
            code = "uncovered_requirement_evidence_line"
            message = "要求 evidence line 没有对应的有效 fact mention 或非职责 clause"
        else:
            continue
        if any(
            source_text in line.source_text or line.source_text in source_text
            for source_text in candidate_sources
        ):
            continue
        diagnostics.append(
            ExtractionCompilationDiagnostic(
                code=code,
                path=f"evidence_lines[{line.index}]",
                message=message,
            )
        )


def _is_heading_only(text: str) -> bool:
    folded = _BULLET_PREFIX.sub("", text).strip().rstrip(":：").casefold()
    responsibility_markers = next(
        markers for kind, markers in _HEADING_MARKERS if kind == "responsibilities"
    )
    return folded in {marker.casefold() for marker in responsibility_markers}


def _section_kind(text: str) -> JDSectionKind | None:
    folded = _BULLET_PREFIX.sub("", text).strip().casefold()
    for kind, markers in _HEADING_MARKERS:
        if any(folded.startswith(marker.casefold()) for marker in markers):
            return kind
    return None


def _looks_like_metadata(text: str) -> bool:
    return bool(
        re.match(
            r"^(?:工作地点|办公地点|岗位类型|职位类型|招聘类型|地点)\s*[:：]",
            _BULLET_PREFIX.sub("", text).strip(),
            flags=re.IGNORECASE,
        )
    )


def _unique(values: list[Any]) -> list[Any]:
    result: list[Any] = []
    seen: set[Any] = set()
    for value in values:
        key = value.casefold() if isinstance(value, str) else value
        if key not in seen:
            result.append(value)
            seen.add(key)
    return result
