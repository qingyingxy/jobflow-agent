from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from typing import ClassVar
from urllib.parse import urljoin, urlsplit

from src.services.url_reader import ParsedHTMLDocument, parse_html_document


class DetailScopeError(ValueError):
    pass


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
            "script",
            "style",
            "template",
            "noscript",
        }
        excluded |= attrs.get("role") in {"navigation", "menu", "contentinfo"}
        excluded |= bool(
            re.search(
                r"similar|recommend|related|breadcrumb|cookie|(?:^|[-_ ])nav(?:$|[-_ ])",
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
_RELATED = re.compile(
    r"^(?:相似职位|相关职位|推荐职位|其他职位|similar jobs|related jobs|recommended jobs)$",
    re.IGNORECASE,
)
_CLOSED = re.compile(
    r"^(?:已结束|已关闭|招聘已结束|职位已下线|岗位已下线|招聘结束|职位已关闭|停止招聘|job closed|position closed|no longer accepting applications)$",
    re.IGNORECASE,
)


def _job_title(text):
    return (
        2 <= len(text) <= 180
        and text
        not in {"基本信息", "基础信息", "在招业务", "职位详情", "岗位详情", "招聘详情"}
        and not _REQUIREMENTS.search(text)
        and not _RELATED.match(text)
        and not re.fullmatch(
            r".*(?:招聘|招聘官网)|careers|jobs|job opportunities", text, re.IGNORECASE
        )
    )


def _titles(root):
    nodes = []
    for node in root.walk():
        label = (node.attrs.get("class", "") + " " + node.attrs.get("id", "")).lower()
        heading = node.tag == "h1" or node.attrs.get("itemprop") == "title"
        heading |= node.tag in {"h2", "h3"} and bool(
            re.search(
                r"工程师|开发|实习生|engineer|developer|analyst|designer",
                node.text(),
                re.IGNORECASE,
            )
        )
        heading |= bool(
            re.search(r"(?:job|position|vacancy|detail).*?(?:title|name)(?:$|[\s_-])", label)
        )
        if (
            heading
            and _job_title(node.text())
            and not any(node.text() == old.text() for old in nodes)
        ):
            nodes.append(node)
    # Nested title wrappers describe the same heading; retain the innermost one.
    return [
        n
        for n in nodes
        if not any(other is not n and other in list(n.walk()) for other in nodes)
    ]


def _select_scope(root):
    # Stop at the next section heading, not at the end of the entire page.
    for node in list(root.walk()):
        if _RELATED.fullmatch(node.text()) and not any(
            isinstance(c, _Node) and _RELATED.fullmatch(c.text()) for c in node.children
        ):
            siblings = node.parent.children
            for sibling in siblings[siblings.index(node):]:
                if not isinstance(sibling, _Node):
                    continue
                if sibling is not node and (
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
    while scope:
        if _REQUIREMENTS.search(scope.text()):
            selected = scope
        # A main region includes sibling qualifications, metadata and status banners.
        if scope.tag == "main" or scope.attrs.get("role") == "main":
            break
        scope = scope.parent
    if selected is not None:
        return selected, title_node
    raise DetailScopeError("未找到当前岗位的职责或任职要求，不能使用网站标题替代")


def _scope_text(node):
    """Serialize every retained text node once, regardless of its HTML tag."""
    if node.excluded:
        return ""
    block = node.tag in {"div", "main", "article", "section", "p", "li", "ul", "ol", "table", "tr", "dl", "dt", "dd", "h1", "h2", "h3", "h4", "br"}
    body = " ".join(_scope_text(c) if isinstance(c, _Node) else c for c in node.children)
    return "\n" + body + "\n" if block else body


def _normalized_scope_text(scope):
    text = _scope_text(scope)
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines() if line.strip())
    # Labels and values are often separate divs; retain their association.
    return re.sub(r"(工作地点|办公地点|招聘类型|招聘项目|公司名称|招聘公司|location|company)[:：]?\n", r"\1：", text, flags=re.IGNORECASE)


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
            and re.sub(r"\s+", "", title_node.text()).casefold()
            != re.sub(r"\s+", "", doc.title).casefold()
        ):
            raise DetailScopeError("页面标题与结构化岗位不一致，需要核实")
    else:
        title = title_node.text()
        text = _normalized_scope_text(scope)
        header = text.split(title, 1)[-1]
        header = _REQUIREMENTS.split(header, maxsplit=1)[0]
        locations = []
        for match in re.finditer(
            r"(?:^|[\s/|])([\u4e00-\u9fff]{2,10}市)(?=[\s/|]|$)", header
        ):
            if match[1] not in locations:
                locations.append(match[1])
        city_list = re.search(
            r"(?:[\u4e00-\u9fff]{2,10}\s*/\s*)+[\u4e00-\u9fff]{2,10}", header
        )
        if city_list and not locations:
            from src.services.discovery_matching import _LOCATION_GROUPS

            known_cities = {group[0] for group in _LOCATION_GROUPS}
            names = city_list[0].replace(" ", "").split("/")
            locations = list(dict.fromkeys(name for name in names if name in known_cities))
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
