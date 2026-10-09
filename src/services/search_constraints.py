"""Small, source-preserving exclusion grammar shared by planning and filtering.

Recognizes explicit exclusions of named alternatives, not arbitrary conditional
preferences. The complete query is still sent to the search provider.
"""

import re

NEGATIVE = re.compile(
    r"(?<!不)(?:不考虑|不接受|不想去|不去|不要|不做|排除|拒绝|除开|除了)"
    r"|\b(?:excluding|exclude|except|not\s+in)\b",
    re.IGNORECASE,
)
END = re.compile(r"[，,；;。\n]|但是|但|只(?:考虑|接受|要)|仅限|优先|首选")


def negative_spans(query):
    spans = []
    for match in NEGATIVE.finditer(query):
        end = END.search(query, match.end())
        spans.append((match.start(), end.start() if end else len(query)))
    return spans


def has_exclusions(query):
    return bool(NEGATIVE.search(query) or re.search(r"除外|不考虑|不要", query))


def term_pattern(term):
    escaped = re.escape(term)
    return rf"(?<![a-z0-9]){escaped}(?![a-z0-9])" if term.isascii() else escaped


def select_term_groups(query, groups):
    """Return positive/excluded alias groups, with exclusions taking precedence."""
    query = query.casefold()
    spans = negative_spans(query)
    positive, excluded = [], []
    for aliases in groups:
        occurrences = [
            m
            for term in aliases
            for m in re.finditer(term_pattern(term.casefold()), query)
        ]
        denied = any(
            any(start <= m.start() < end for start, end in spans)
            or re.match(
                r"\s*(?:市|地区|岗位|职位)?\s*(?:都)?(?:不考虑|不接受|不要|除外)",
                query[m.end() :],
            )
            for m in occurrences
        )
        if denied:
            excluded.append(aliases)
        elif occurrences:
            positive.append(aliases)
    return positive, excluded
