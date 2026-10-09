"""Runtime safeguards for facts whose role cannot be established by a date alone."""

import re

from src.domain.job import StructuredJobDescription

_DATE = re.compile(
    r"(?<!\d)(20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})日?(?!\d)"
)
_DEADLINE = re.compile(
    r"(?:截止(?:日期|时间)?|(?:申请|报名|投递|网申)结束(?:日期|时间)?|application\s+deadline|closing\s+date|apply\s+by)\s*[:：为是]?\s*$",
    re.IGNORECASE,
)


def ground_runtime_facts(structured: StructuredJobDescription, raw_content: str):
    if structured.deadline is None:
        return structured
    expected = (
        structured.deadline.year,
        structured.deadline.month,
        structured.deadline.day,
    )
    for match in _DATE.finditer(raw_content):
        if tuple(map(int, match.groups())) != expected:
            continue
        before = raw_content[max(0, match.start() - 60) : match.start()]
        after = raw_content[match.end() : match.end() + 16]
        clause = re.split(r"[。；;\n]", before)[-1]
        if re.search(r"(?:毕业|入学|出生|报到|到岗|入职)", clause):
            continue
        if _DEADLINE.search(before) or re.match(
            r"\s*(?:前|之前)?\s*(?:截止|停止(?:报名|投递|申请))", after
        ):
            return structured
    # Preserve historical parser output, but never expose an unsupported date
    # as a deadline in the product, including when reading a cached analysis.
    return structured.model_copy(
        update={
            "deadline": None,
            "field_evidence": [
                e for e in structured.field_evidence or [] if e.field_path != "deadline"
            ]
            or None,
        }
    )
