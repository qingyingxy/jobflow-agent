"""Discover listing capabilities from public pages, independent of company IDs."""

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from src.services.job_detail_scope import _Page
from src.services.job_url import canonical_job_url
from src.services.lead_presentation import discovery_kind, reference_link_reason
from src.services.recruitment_trust import ats_jobs_route, hiring_scope, within_scope
from src.services.url_reader import HTMLLink

_NEXT = re.compile(
    r"^(?:下一页|下页|加载更多|更多职位|next(?: page)?|load more)[\s›»>]*$",
    re.IGNORECASE,
)
_VIEW_JOBS = re.compile(r"^(?:(?:查看|浏览|全部|搜索|进入)(?:在招|工作)?(?:\s*\d+\s*个?)?(?:职位|岗位)|(?:view|browse|all|search)\s+(?:\d+\s+)?jobs)[\s→›»>]*$", re.IGNORECASE)
_RECRUITING_CONTROL = re.compile(r"^(?:\d{4}(?:届)?\s*)?(?:校园招聘|应届生招聘|应届校招|实习生招聘|社会招聘)(?:与实习)?[\s→›»]*$")
_MORE_CONTROL = re.compile(r"^(?:了解更多|点击查看|马上启程|learn more|view more)[\s→›»>]*$", re.IGNORECASE)
_ENTRY = re.compile(
    r"招聘|校招|应届|实习|职位|岗位|加入我们|careers?|jobs?|positions?|campus|internship",
    re.IGNORECASE,
)
_ACTION = re.compile(
    r"(?:^|/)(?:apply|application|login|signin|register|logout)(?:/|$)", re.IGNORECASE
)


def navigation_action(url):
    parsed = urlsplit(url)
    public_apply_portal = parsed.path.startswith("/apply/") and ats_jobs_route(url)
    return bool(_ACTION.search(parsed.path) and not public_apply_portal)


def listing_document_url(url, requested):
    """Restore an observed SPA route only for its identical HTTP document."""
    target, origin = urlsplit(url), urlsplit(requested)
    if origin.fragment and not target.fragment and origin._replace(fragment="") == target:
        return requested
    return url


class _ListingDOM(_Page):
    def __init__(self):
        super().__init__()
        self.entry_buttons = []

    def handle_starttag(self, tag, attrs):
        super().handle_starttag(tag, attrs)
        # Finding entrances needs navigation/footer links. Detail extraction's
        # semantic exclusions must not remove them from the discovery tree.
        node = self.current
        style = re.sub(r"\s+", "", node.attrs.get("style") or "").lower()
        node.excluded = ("hidden" in node.attrs or node.attrs.get("aria-hidden") == "true"
                         or "display:none" in style or "visibility:hidden" in style
                         or tag in {"head", "title", "script", "style", "template", "noscript"})
        if tag == "button" or self.current.attrs.get("role") == "button":
            self.entry_buttons.append(self.current)
        # Pagination often lives in a nav. Keep it for control discovery only;
        # job cards in navigation are still excluded below.
        if tag == "nav":
            node = self.current
            style = re.sub(r"\s+", "", node.attrs.get("style") or "").lower()
            node.excluded = (
                "hidden" in node.attrs
                or node.attrs.get("aria-hidden") == "true"
                or "display:none" in style
                or "visibility:hidden" in style
            )


def same_origin(url, expected):
    left, right = urlsplit(url), urlsplit(expected)
    return (left.scheme, left.netloc) == (right.scheme, right.netloc)


def allowed_listing_url(url, base, *, allow_documents=False):
    """Same employer origin or the exact ATS tenant, without action endpoints."""
    try:
        parsed, origin = urlsplit(url), urlsplit(base)
        default_ports = (
            parsed.port in {None, 443 if parsed.scheme == "https" else 80}
            and origin.port in {None, 443 if origin.scheme == "https" else 80}
        )
    except ValueError:
        return False
    scope = hiring_scope(base)
    return bool(
        parsed.scheme in {"http", "https"}
        and not parsed.username
        # Public recruitment sites sometimes redirect between HTTP and HTTPS.
        # Keep the exact host and tenant; scheme changes need default ports.
        and parsed.hostname == origin.hostname
        and (same_origin(url, base) or default_ports)
        and (not scope or within_scope(url, scope))
        and not navigation_action(url)
        and (not reference_link_reason(url) or allow_documents and reference_link_reason(url) in {
            'article_or_discussion', 'attachment_or_document'})
    )


def observed_hiring_redirect(requested, final, chain):
    """Accept a recorded HTTP redirect to one ATS tenant, never a guessed move."""
    if hiring_scope(requested) or not hiring_scope(final) or not chain:
        return False
    expected, scope = canonical_job_url(requested), hiring_scope(final)
    for edge in chain:
        if edge.get("status") not in {301, 302, 303, 307, 308} or canonical_job_url(edge.get("url", "")) != expected:
            return False
        target = edge.get("target", "")
        if not allowed_listing_url(target, requested) and not (within_scope(target, scope) and allowed_listing_url(target, final)):
            return False
        expected = canonical_job_url(target)
    return allowed_listing_url(final, expected)


def allowed_entry_navigation(url, origin):
    """An observed public hiring control may reveal an external entry, not trust it."""
    from src.services.company_entry_resolution import permitted_entry

    return allowed_listing_url(url, origin) or bool(
        not hiring_scope(origin) and permitted_entry(url)
        and not reference_link_reason(url) and not navigation_action(url)
    )


def _ancestors(node):
    while node:
        yield node
        node = node.parent


def _disabled(node):
    return any(
        "disabled" in n.attrs
        or n.attrs.get("aria-disabled") == "true"
        or re.search(r"(?:^|[\s_-])disabled(?:$|[\s_-])", n.attrs.get("class") or "")
        for n in _ancestors(node)
    )


def _outside_job_list(node):
    return any(n.tag in {"nav", "footer", "aside", "form"}
               or n.attrs.get("role") in {"navigation", "menu", "contentinfo"}
               or re.search(r"footer|recommend|related|(?:^|[-_ ])nav(?:$|[-_ ])",
                            n.attrs.get("class", "") + " " + n.attrs.get("id", ""), re.IGNORECASE)
               for n in _ancestors(node))


@dataclass(frozen=True)
class ListingCapabilities:
    jobs: tuple[HTMLLink, ...]
    entries: tuple[HTMLLink, ...]
    next_urls: tuple[str, ...]
    pagination_unresolved: bool
    entry_controls: bool = False
    job_controls: bool = False
    outbound_jobs: tuple[HTMLLink, ...] = ()


def listing_card_texts(raw_html, *, url, job_urls):
    """Read only the observed card around one job link, for ranking, not proof."""
    page = _ListingDOM()
    page.feed(raw_html)
    targets = {canonical_job_url(target) for target in job_urls}
    result = {}
    for node in page.root.walk():
        if node.tag != "a" or not node.attrs.get("href"):
            continue
        target = canonical_job_url(urljoin(url, node.attrs["href"]))
        if target not in targets:
            continue
        text = node.text()
        for parent in list(_ancestors(node.parent))[:4]:
            linked = {canonical_job_url(urljoin(url, child.attrs["href"])) for child in parent.walk()
                      if child.tag == "a" and child.attrs.get("href")} & targets
            if linked != {target} or len(parent.text()) > 1500:
                break
            if parent.tag in {"li", "article"} or re.search(r"(?:job|position|post|vacancy)[\w-]*(?:card|item|row)", parent.attrs.get("class", ""), re.IGNORECASE):
                text = parent.text()
                break
        result[target] = text
    return result


def inspect_listing(raw_html, *, url):
    page = _ListingDOM()
    page.feed(raw_html)
    jobs, entries, outbound_jobs, next_urls = {}, {}, {}, set()
    pagination_unresolved = False
    job_controls = False
    title_class = re.compile(r"(?:job|position|pos|post|vacancy)[\w-]*(?:title|name)|(?:^|[\s_-])(?:title|name)(?:$|[\s_-])", re.IGNORECASE)
    card_class = re.compile(r"(?:job|position|pos|post|vacancy|list)[\w-]*(?:card|item|row)", re.IGNORECASE)
    generic_card = re.compile(r"(?:^|[\s_-])(?:item|card|row)(?:$|[\s_-])", re.IGNORECASE)
    # Detail extraction excludes recommendation regions. A campus homepage can
    # legitimately use one for its main "view jobs" entry. This is only a hint
    # to inspect visible browser controls, never evidence for a job.
    entry_controls = any(
        _VIEW_JOBS.fullmatch(node.text()) and not _disabled(node)
        and not any(n.tag in {"form", "footer", "aside", "template", "script"}
                    or "hidden" in n.attrs or n.attrs.get("aria-hidden") == "true"
                    for n in _ancestors(node))
        for node in page.entry_buttons
    )
    for node in page.root.walk():
        # A hint to inspect a visible control, never a fabricated navigation URL.
        control = (node.tag in {"button", "a"} or node.attrs.get("role") in {"button", "link"}
                   or "onclick" in node.attrs or re.search(r"cursor\s*:\s*pointer", node.attrs.get("style", "")))
        if control and not node.attrs.get("href") and not _disabled(node):
            parents = list(_ancestors(node))
            text = node.text().strip()
            safe = not any(n.tag in {"form", "footer", "aside", "template", "script"} or n.excluded for n in parents)
            selected = node.attrs.get("aria-selected") == "true" or node.attrs.get("aria-current") == "page"
            contextual_more = _MORE_CONTROL.fullmatch(text) and any(
                len(p.text()) < 500 and re.search(r"校园|应届|校招|实习|graduate|campus", p.text(), re.IGNORECASE)
                for p in parents[1:5])
            if safe and not selected and (_VIEW_JOBS.fullmatch(text) or _RECRUITING_CONTROL.fullmatch(text) or contextual_more):
                entry_controls = True
        structural = any(
            generic_card.search(parent.attrs.get("class", "")) and parent.text().startswith(node.text())
            and re.search(r"工作地点|所属业务|岗位职责|工作职责|location|department", parent.text(), re.IGNORECASE)
            for parent in list(_ancestors(node.parent))[:3]
        ) if node.tag in {"span", "h2", "h3", "h4"} and 3 <= len(node.text()) <= 140 else False
        if structural and re.search(r"工程师|研究员|产品经理|engineer|developer|scientist", node.text(), re.IGNORECASE) and not _outside_job_list(node):
            job_controls = True
        if (title_class.search(node.attrs.get("class", "")) and len(node.text()) <= 140
                and re.search(r"工程师|研究员|开发|算法|产品经理|分析师|engineer|developer|scientist", node.text(), re.IGNORECASE)
                and any(card_class.search(parent.attrs.get("class", "")) for parent in list(_ancestors(node.parent))[:5])
                and not _outside_job_list(node)):
            job_controls = True
        if node.tag not in {"a", "button"} and node.attrs.get("role") != "button":
            continue
        if _disabled(node):
            continue
        label = node.attrs.get("aria-label") or node.attrs.get("title") or node.text().strip()
        if not label:
            label = " ".join(child.attrs.get("alt", "") for child in node.walk() if child.tag == "img").strip()
        if _VIEW_JOBS.fullmatch(label) and not node.attrs.get("href") and not any(n.tag == "form" for n in _ancestors(node)):
            entry_controls = True
        is_next = bool(
            _NEXT.fullmatch(label) or "next" in (node.attrs.get("rel") or "").split()
        )
        href = node.attrs.get("href") or ""
        target = canonical_job_url(urljoin(url, href)) if href else None
        valid_href = bool(
            href
            and not href.startswith(("javascript:", "#"))
            or href.startswith(("#/", "#!/"))
        )
        if is_next:
            if (
                valid_href
                and allowed_listing_url(target, url)
                and target != canonical_job_url(url)
            ):
                next_urls.add(target)
            else:
                pagination_unresolved = True
            continue
        campus_portal = bool(target and hiring_scope(target) and re.search(r"/(?:campus|school|graduate|edu)(?:[-_/?.#]|$)", target, re.IGNORECASE))
        if node.tag != "a" or not valid_href or not target or (not label and not ats_jobs_route(target) and not campus_portal):
            continue
        # An outbound ATS entry is only a candidate here. The caller must bind
        # it to the trusted employer page before reading it.
        local = allowed_listing_url(target, url)
        from src.services.company_entry_resolution import permitted_entry

        outbound = (not hiring_scope(url) and not same_origin(target, url)
                    and permitted_entry(target) and not navigation_action(target))
        if not local and not outbound:
            continue
        if (
            discovery_kind(target, label, observed_title=True) == "job"
            and not _outside_job_list(node)
        ):
            if local:
                jobs[target] = HTMLLink(target, label)
            elif hiring_scope(target):
                # A public employer page may link directly to specific ATS
                # jobs. Preserve only these observed URLs, never the ATS host.
                outbound_jobs[target] = HTMLLink(target, label)
        elif (discovery_kind(target, label, observed_title=True) != "job"
              and not navigation_action(target)):
            context = label
            if re.fullmatch(r"(?:立即)?(?:投递|申请)(?:职位|岗位)?[\s→›»]*", label) or _MORE_CONTROL.fullmatch(label):
                # A navigation link is not a form submission. Associate a short
                # CTA with its own recruitment section, not the whole document.
                for parent in list(_ancestors(node.parent))[:4]:
                    text = parent.text()
                    if len(text) <= 500 and _ENTRY.search(text):
                        context = text
                        break
            if ((_ENTRY.search(context + " " + urlsplit(target).path) or ats_jobs_route(target) or campus_portal)
                    and not re.search(r"\.(?:pdf|docx?|xlsx?|zip)$", urlsplit(target).path, re.IGNORECASE)):
                entries[target] = HTMLLink(target, context)
    if len(next_urls) > 1:
        pagination_unresolved = True
        next_urls.clear()  # Never choose between ambiguous next-page controls.
    return ListingCapabilities(
        tuple(jobs.values()),
        tuple(entries.values()),
        tuple(sorted(next_urls)),
        pagination_unresolved, entry_controls, job_controls, tuple(outbound_jobs.values()),
    )


def recruitment_priority(link, job_types):
    """Use explicit recruitment sections to schedule, never to verify a job."""
    text = link.text.casefold()
    path = urlsplit(link.url).path.casefold()
    # Informational pages are useful context, but must not displace a job list
    # or prevent its dynamic cards from being opened.
    if (re.search(r"常见问题|招聘流程|招聘须知|宣讲|招聘新闻", text)
            or re.search(r"/(?:faq|news|help|process)(?:/|$)", path)):
        return 2
    social = bool(
        re.search(r"社招|社会招聘", text)
        or re.search(r"/(?:social|experienced)(?:[-_/]|$)", path)
    )
    campus = bool(
        re.search(r"校招|校园|应届", text)
        or re.search(r"/(?:campus|graduate)[^/]*(?:/|$)", path)
    )
    intern = bool(
        re.search(r"实习", text) or re.search(r"/(?:intern|internship)(?:/|$)", path)
    )
    if job_types == ["校招"]:
        combined_entry = bool(re.search(r"校园招聘[与及和/、]实习", text))
        if campus and social:
            return 1  # Contradictory navigation labels need actual job details.
        return 2 if social or (intern and not combined_entry) else 0 if campus else 1
    if job_types == ["实习"]:
        return 0 if intern else 2 if social else 1  # Internships can live under campus.
    return 1


def entry_priority(link, job_types, query):
    """Regional portals are navigation, not evidence of recruitment type."""
    from src.services.discovery_matching import search_filter_conditions

    locations = search_filter_conditions(query).get("locations", [])
    if locations and re.search(r"(?:careers?|jobs?)\s+(?:in|for)\s+(?:china|中国)|中国(?:招聘|职位)|中国区", link.text, re.IGNORECASE):
        return 0
    return recruitment_priority(link, job_types)


def feishu_filters(page, *, base):
    """A protocol fingerprint from observed responses, never an employer name."""
    for record in reversed(getattr(page, "recruitment_api", ())):
        payload = record.get("payload")
        if (
            same_origin(record.get("url", ""), base)
            and re.fullmatch(
                r"/api/v1/config/job/filters/\d+", urlsplit(record["url"]).path
            )
            and isinstance(payload, dict)
            and payload.get("code") == 0
            and isinstance(payload.get("data"), dict)
        ):
            return payload["data"]
    return None


def observed_ats_base(page, capabilities):
    """A protocol's route prefix comes from observed detail URLs, not a brand."""
    parsed = urlsplit(page.final_url)
    bases = set()
    for link in capabilities.jobs:
        match = re.fullmatch(r"(.+)/position/[^/]+/detail/?", urlsplit(link.url).path)
        if match and same_origin(link.url, page.final_url):
            base = match.group(1)
            if parsed.path.rstrip("/") in {base, base + "/position", base + "/position/list"}:
                bases.add(base)
    if len(bases) == 1:
        # Keep the observed list route. Dropping /position/list can open a
        # company introduction page that never submits the requested filters.
        return parsed._replace(path=parsed.path.rstrip("/"), query="", fragment="").geturl()
    if (re.fullmatch(r"/(?:campus|internship|\d+)/?(?:position(?:/list)?)?/?", parsed.path)
            and any(urlsplit(r.get("url", "")).path == "/api/v1/search/job/posts" for r in getattr(page, "recruitment_api", ()))):
        return parsed._replace(path=parsed.path.rstrip("/"), query="", fragment="").geturl()
    return None
