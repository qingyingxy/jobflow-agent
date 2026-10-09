"""Keep SPA routes while dropping ordinary in-page anchors."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def route_fragment(fragment):
    return fragment if fragment.startswith(("/", "!/")) else ""


def canonical_job_url(url: str) -> str:
    """One identity for discovery, persistence and queues; retain job selectors."""

    def clean_query(query):
        return urlencode(
            sorted(
                (key, value)
                for key, value in parse_qsl(query, keep_blank_values=True)
                if not key.casefold().startswith("utm_")
                and key.casefold() not in {"gclid", "fbclid", "msclkid"}
            ),
            safe="()",
        )

    parsed = urlsplit(url.strip())
    fragment = route_fragment(parsed.fragment)
    if fragment:
        prefix = "!" if fragment.startswith("!") else ""
        route = urlsplit(fragment.removeprefix("!"))
        fragment = prefix + urlunsplit(
            ("", "", route.path, clean_query(route.query), "")
        )
    return urlunsplit(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path or "/",
            clean_query(parsed.query),
            fragment,
        )
    )
