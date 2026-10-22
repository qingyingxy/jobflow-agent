from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urljoin, urlsplit

from src.services.job_header_facts import header_location_evidence
from src.services.url_reader import ParsedHTMLDocument, parse_html_document


class DetailScopeError(ValueError):
    pass


EXTRACTOR_VERSION = "generic-job-scope-v6-header-boundaries"


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    parent: _Node | None = None
    children: list = field(default_factory=list)
    excluded: bool = False

    def text(self):
        if self.excluded:
            return ""
        return " ".join(
            x.text() if isinstance(x, _Node) else x for x in self.children
        ).strip()

    def walk(self):
        if not self.excluded:
            yield self
            for child in self.children:
                if isinstance(child, _Node):
                    yield from child.walk()


class _Page(HTMLParser):
    void: ClassVar[set[str]] = {
        "img",
        "input",
        "br",
        "hr",
        "meta",
        "link",
        "source",
        "wbr",
        "area",
        "base",
        "embed",
        "param",
        "track",
        "col",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document")
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        label = (attrs.get("class", "") + " " + attrs.get("id", "")).lower()
        hidden = "hidden" in attrs or attrs.get("aria-hidden") == "true"
        style = re.sub(r"\s+", "", attrs.get("style", "")).lower()
        excluded = hidden or "display:none" in style or "visibility:hidden" in style
        excluded |= tag in {
            "nav",
            "footer",
            "aside",
            "head",
            "title",
            "script",
            "style",
            "template",
            "noscript",
        }
        excluded |= attrs.get("role") in {"navigation", "menu", "contentinfo"}
        excluded |= bool(
            re.search(
                r"similar|recommend|related|breadcrumb|cookie|footer|(?:^|[-_ ])nav(?:$|[-_ ])",
                label,
            )
        )
        node = _Node(tag, attrs, self.current, excluded=excluded)
        self.current.children.append(node)
        if tag not in self.void:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        if data.strip():
            self.current.children.append(re.sub(r"\s+", " ", data).strip())


_REQUIREMENTS = re.compile(
    r"岗位职责|工作职责|职位描述|职位职责|任职要求|岗位要求|职位要求|职责描述|responsibilities|qualifications|requirements|job description",
    re.IGNORECASE,
)
_QUALIFICATIONS = re.compile(r"任职要求|岗位要求|职位要求|职责要求|任职资格|工作要求|qualifications|requirements", re.IGNORECASE)
_RELATED = re.compile(
    r"^(?:(?:相似|相关|推荐|其他)(?:职位|岗位)(?:推荐)?|similar jobs|related jobs|recommended jobs)$",
    re.IGNORECASE,
)
_CLOSED = re.compile(
    r"^(?:(?:该|此|本)?(?:职位|岗位)(?:已下线|已关闭|已结束|已停止招聘)|已结束|已关闭|招聘已结束|招聘结束|停止招聘|job closed|position closed|no longer accepting applications)[。.!！]?$",
    re.IGNORECASE,
)
_TITLE_BADGE = re.compile(r"^(?:热招|急招|新|急|招聘中|已结束|已关闭|hot|new|urgent)$", re.IGNORECASE)
_HEADER_FIELD = re.compile(r"^(?:职位类别|岗位类别|职能类别|工作地点|招聘人数|招聘类型|岗位状态|职位状态|job category|location)\s*[:：]", re.IGNORECASE)
_FIELD_HEADING = re.compile(
    r"^(?:工作城市|工作地点|工作地区|工作地址|职位类别|岗位类别|职能类别|招聘人数|招聘类型|"
    r"岗位状态|职位状态|招聘状态|招聘对象|毕业时间|届别要求|适用届别|学历要求|工作经验|"
    r"所属部门|发布时间|截止时间|薪资范围|职位信息|岗位信息|"
    r"locations?|job locations?|job category|employment type|department|education|experience)\s*[:：]?$",
    re.IGNORECASE,
)
_JOB_COMPONENT = re.compile(r"job|position|vacancy|detail|(?:^|[\s_-])(?:pos|post)(?:$|[\s_-])", re.IGNORECASE)
_UTILITY_HEADING = re.compile(
    r"(?:方式\s*\d+\s*[:：]\s*)?(?:分享|复制|收藏|申请|投递)(?:岗位|职位)(?:链接|海报)?"
    r"|(?:share|copy|save|apply for)\s+(?:this\s+|the\s+)?(?:job|position)(?:\s+link)?",
    re.IGNORECASE,
)


def _title_text(node):
    """Keep the literal title while leaving nested metadata in the body evidence."""
    def parts(current):
        if current.excluded:
            return []
        result = []
        for child in current.children:
            if isinstance(child, str):
                result.append(child)
            elif not (_TITLE_BADGE.fullmatch(child.text()) or _HEADER_FIELD.match(child.text())):
                result.extend(parts(child))
        return result

    return " ".join(parts(node)).strip()


def _ancestors(node):
    while node:
        yield node
        node = node.parent


def _nearest_duties(node):
    return next((parent for parent in _ancestors(node.parent) if _REQUIREMENTS.search(parent.text())), None)


def _job_title(text):
    return (
        2 <= len(text) <= 180
        and text
        not in {"基本信息", "基础信息", "在招业务", "职位详情", "岗位详情", "招聘详情"}
        and not _REQUIREMENTS.search(text)
        and not _QUALIFICATIONS.search(text)
        and not _RELATED.match(text)
        and not _CLOSED.fullmatch(text)
        and not _TITLE_BADGE.fullmatch(text)
        and not _HEADER_FIELD.match(text)
        and not _FIELD_HEADING.fullmatch(text)
        and not _UTILITY_HEADING.fullmatch(text)
        and not re.fullmatch(
            r".*(?:招聘|招聘官网)|careers|jobs|job opportunities", text, re.IGNORECASE
        )
    )


def _titles(root):
    nodes = []
    for node in root.walk():
        label = (node.attrs.get("class", "") + " " + node.attrs.get("id", "")).lower()
        heading = node.tag == "h1" or node.attrs.get("itemprop") == "title" or node.attrs.get("role") == "heading"
        heading |= node.tag in {"h2", "h3"} and bool(
            re.search(
                r"工程师|开发|实习生|engineer|developer|analyst|designer",
                node.text(),
                re.IGNORECASE,
            )
        )
        heading |= bool(
            re.search(r"(?:job|position|vacancy|detail|(?:^|[\s_-])(?:pos|post)).*?(?:title|name|tit)(?:$|[\s_-])", label)
            and not re.search(r"(?:^|[\s_-])sub[\s_-]*title(?:$|[\s_-])", label)
        )
        # Short component headings need a surrounding recruitment component.
        heading |= bool(
            re.search(r"(?:^|[\s_-])(?:title|name|tit)(?:$|[\s_-])", label)
            and any(_JOB_COMPONENT.search(parent.attrs.get("class", "") + " " + parent.attrs.get("id", ""))
                    for parent in _ancestors(node.parent))
            and not re.search(r"(?:^|[\s_-])sub[\s_-]*title(?:$|[\s_-])", label)
        )
        if (
            heading
            and _job_title(_title_text(node))
        ):
            nodes.append(node)
    # Nested title wrappers describe the same heading; retain the innermost one.
    nodes = [
        n
        for n in nodes
        if not any(other is not n and other in list(n.walk()) for other in nodes)
    ]
    # Sticky and mobile headings may repeat the same job. Prefer the copy whose
    # body is more local; identical titles on independent job bodies stay ambiguous.
    scopes = {node: _nearest_duties(node) for node in nodes}
    result = []
    for node in nodes:
        peers = [other for other in nodes if other is not node and _title_text(other) == _title_text(node)]
        scope = scopes[node]
        if scope is not None and any(scopes[other] is not None and scopes[other] is not scope
                                     and scope in _ancestors(scopes[other].parent) for other in peers):
            continue
        if scope is not None and any(scopes[old] is scope and _title_text(old) == _title_text(node) for old in result):
            continue
        result.append(node)
    return result


def _select_scope(root):
    # Stop at the next section heading, not at the end of the entire page.
    for node in list(root.walk()):
        if _RELATED.fullmatch(node.text()) and not any(
            isinstance(c, _Node) and _RELATED.fullmatch(c.text()) for c in node.children
        ):
            # A section label can sit inside otherwise empty layout wrappers.
            # Its following job cards are siblings of the wrapper, not the label.
            boundary = node
            while boundary.parent and _RELATED.fullmatch(boundary.parent.text()):
                boundary = boundary.parent
            if boundary.parent is None:
                continue
            siblings = boundary.parent.children
            for sibling in siblings[siblings.index(boundary):]:
                if not isinstance(sibling, _Node):
                    continue
                if sibling is not boundary and (
                    sibling.tag in {"h1", "h2", "h3", "h4"}
                    and _REQUIREMENTS.search(sibling.text())
                ):
                    break
                sibling.excluded = True
    titles = _titles(root)
    if len(titles) != 1:
        raise DetailScopeError("无法唯一确定当前岗位名称；保留链接待核验")
    title_node = titles[0]
    scope = title_node.parent
    selected = None
    detail_container = None
    has_qualifications = bool(_QUALIFICATIONS.search(root.text()))
    main = next((parent for parent in _ancestors(scope) if parent.tag == "main" or parent.attrs.get("role") == "main"), None)
    while scope:
        complete = _REQUIREMENTS.search(scope.text()) and (not has_qualifications or _QUALIFICATIONS.search(scope.text()))
        if complete and (selected is None or scope is main):
            # Prefer the nearest complete job body. Extending to the document
            # root can import navigation labels such as campus/social hiring.
            selected = scope
        # A main region includes sibling qualifications, metadata and status banners.
        if scope.tag == "main" or scope.attrs.get("role") == "main":
            break
        if main is None and complete and re.search(
            r"(?:job|position|vacancy|pos|post)[-_ ]?detail.*?(?:wrap|inner|container|content)(?:$|[\s_-])|(?:^|[\s_-])detail[-_ ](?:wrapper|wrap|inner|container|content)(?:$|[\s_-])",
            scope.attrs.get("class", "") + " " + scope.attrs.get("id", ""), re.IGNORECASE,
        ):
            detail_container = scope
        scope = scope.parent
    if selected is not None:
        return detail_container or selected, title_node
    raise DetailScopeError("未找到当前岗位的职责或任职要求，不能使用网站标题替代")


def _scope_text(node):
    """Serialize every retained text node once, regardless of its HTML tag."""
    if node.excluded:
        return ""
    block = node.tag in {"div", "main", "article", "section", "p", "li", "ul", "ol", "table", "tr", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "br"}
    body = " ".join(_scope_text(c) if isinstance(c, _Node) else c for c in node.children)
    return "\n" + body + "\n" if block else body


def readable_page_text(raw_html):
    """Preserve paragraph boundaries for text recovery without assuming a JD template."""
    page = _Page()
    page.feed(raw_html)
    return _normalized_scope_text(page.root)


def _normalized_scope_text(scope):
    from src.services.recruitment_semantics import labelled_fields

    text = _scope_text(scope)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())
    text += "".join("\n" + field.source_text for field in labelled_fields(scope)
                    if field.source_text not in text)
    # Labels and values are often separate divs; retain their association.
    return re.sub(r"(工作地点|办公地点|招聘类型|招聘项目|公司名称|招聘公司|location|company)[:：]?\n", r"\1：", text, flags=re.IGNORECASE)


def closed_page_notice(raw_html: str, *, url: str) -> str | None:
    """A current detail can be closed after the site removes its title and JD.

    Never use a listing's cards, hidden banners or related-job regions as proof.
    """
    from src.services.lead_presentation import discovery_kind

    if discovery_kind(url) != "job":
        return None
    page = _Page()
    page.feed(raw_html)
    # Apply the same related-section exclusions as regular detail extraction.
    try:
        _select_scope(page.root)
    except DetailScopeError:
        pass
    if len(_titles(page.root)) > 1:
        return None
    return next((n.text() for n in page.root.walk() if _CLOSED.fullmatch(n.text())), None)


def _structured(document, url):
    jobs = []
    for item in document.json_ld:
        types = item.get("@type", [])
        types = types if isinstance(types, list) else [types]
        if "JobPosting" in types:
            jobs.append(item)
    exact = [
        j
        for j in jobs
        if isinstance(j.get("url"), str)
        and urljoin(url, j["url"]).rstrip("/") == url.rstrip("/")
    ]
    selected = exact[0] if len(exact) == 1 else jobs[0] if len(jobs) == 1 else None
    if jobs and selected is None:
        raise DetailScopeError("页面含多个岗位，无法确定哪个对应当前链接")
    if (
        selected is None
        or not selected.get("description")
        or not _job_title(str(selected.get("title", "")))
    ):
        return None
    if selected.get("url") and not exact:
        raise DetailScopeError("结构化岗位链接与当前页面不一致")
    payload = json.dumps(selected, ensure_ascii=True).replace("<", "\\u003c")
    return parse_html_document(
        '<script type="application/ld+json">' + payload + "</script>"
    )


def scope_job_document(raw_html: str, document: ParsedHTMLDocument, *, url: str):
    """Site-independent JSON-LD / DOM extraction. Never uses site title as job title."""
    from src.services.lead_presentation import explicit_listing_url

    if explicit_listing_url(url):
        raise DetailScopeError("当前网址是职位列表或搜索入口，不能将单张卡片当作岗位详情")
    page = _Page()
    page.feed(raw_html)
    structured = _structured(document, url)
    try:
        scope, title_node = _select_scope(page.root)
    except DetailScopeError:
        if structured is None:
            raise
        scope, title_node = None, None
    if structured is not None:
        # Description metadata owns the JD; surrounding navigation never enters it.
        doc = structured
        if scope is not None:
            scoped_text = _normalized_scope_text(scope)
            if scoped_text not in doc.text:
                doc = replace(doc, text=doc.text + "\n" + scoped_text)
        if (
            title_node
            and re.sub(r"\s+", "", _title_text(title_node)).casefold()
            != re.sub(r"\s+", "", doc.title).casefold()
        ):
            raise DetailScopeError("页面标题与结构化岗位不一致，需要核实")
    else:
        title = _title_text(title_node)
        text = _normalized_scope_text(scope)
        header = text.split(title, 1)[-1]
        header = _REQUIREMENTS.split(header, maxsplit=1)[0]
        locations = [item["value"] for item in header_location_evidence(text, title)]
        # Legacy compact headers can pair a city with a job category/headcount.
        # Do not retain only known cities from a partly understood location list.
        for match in re.finditer(
            r"(?:^|\n)([\u4e00-\u9fff]{2,10}市)\s*/\s*"
            r"(?:技术|研发|产品|设计|运营|市场|销售|职能)\s*/\s*\d+\s*人", header
        ):
            if match[1] not in locations:
                locations.append(match[1])
        from src.services.job_fact_verifier import _body_job_type

        job_type = _body_job_type(header)
        route = urlsplit(url).path.lower().split("/")
        if job_type is None and "social" in route:
            job_type = "full_time"
        elif job_type is None and "campus" in route:
            job_type = "campus"
        elif job_type is None and "internship" in route:
            job_type = "internship"
        company = None
        from src.services.company_registry import enabled_company_sources

        sources = [
            s
            for s in enabled_company_sources()
            if urlsplit(s.career_url).hostname == urlsplit(url).hostname
        ]
        if len({s.company for s in sources}) == 1:
            company = sources[0].company
        doc = replace(
            document,
            title=title,
            company=company,
            locations=locations,
            job_type=job_type,
            text=text,
            json_ld=[],
        )
    closed = bool(scope and any(_CLOSED.fullmatch(n.text()) for n in scope.walk()))
    if closed and "岗位状态：已结束" not in doc.text:
        doc = replace(doc, text=doc.text + "\n岗位状态：已结束")
    return doc, closed
