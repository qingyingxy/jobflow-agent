"""Keep SPA routes while dropping ordinary in-page anchors."""

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def has_job_selector(path, query):
    selectors = {"jobid", "positionid", "postid", "requisitionid", "reqid"}
    return (any(k.casefold() in selectors and re.fullmatch(r"[\w-]+", v or "")
                for k, v in parse_qsl(query))
            or bool(re.search(r"/(?:jobs?|positions?|posts?|requisitions?)/(?:detail/)?[\w-]*\d[\w-]*(?:/detail)?/?$", path, re.IGNORECASE)))


def route_fragment(fragment):
    return fragment if fragment.startswith(("/", "!/")) else ""


def canonical_job_url(url: str) -> str:
    """One identity for discovery, persistence and queues; retain job selectors."""

    def clean_query(query, path):
        # These are list navigation filters only when a detail already names a
        # job. Keep channel, city, locale, cohort and all unknown selectors.
        list_filters = {"deptcodes", "departmentcodes", "pageindex", "pagenum", "pagesize", "searchkeyword"}
        identified = has_job_selector(path, query)
        return urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
                and key.casefold() not in {"gclid", "fbclid", "msclkid", "spread"}
                and not (identified and key.casefold() in list_filters)
            ),
            safe="()",
        )

    parsed = urlsplit(url.strip())
    fragment = route_fragment(parsed.fragment)
    if fragment:
        prefix = "!" if fragment.startswith("!") else ""
        route = urlsplit(fragment.removeprefix("!"))
        fragment = prefix + urlunsplit(
            ("", "", route.path, clean_query(route.query, route.path), "")
        )
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            clean_query(parsed.query, parsed.path),
            fragment,
        )
    )
