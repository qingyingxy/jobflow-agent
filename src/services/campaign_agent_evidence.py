"""Record observed URLs and their origins without deciding employer ownership."""
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit, urlunsplit

from src.services.url_reader import HTMLLink

MAX_REFERENCES = 350


def public_url(value):
    """Syntax only; the HTTP/browser readers also validate DNS and redirects."""
    try:
        p = urlsplit(value)
        if (p.scheme not in {"http", "https"} or not p.hostname or p.username or p.password
                or p.port not in {None, 80 if p.scheme == "http" else 443}):
            return None
        return urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, p.fragment))
    except (ValueError, TypeError):
        return None


def page_references(page):
    """Expose hyperlinks and literal text addresses without ranking by URL words."""
    refs = {}
    for link in page.get("links", []):
        url = public_url(link.url)
        if url:
            refs[url] = {"url": url, "text": link.text[:300], "kind": "hyperlink"}
    # A bare address in a recruitment announcement is still an observed address.
    # Chinese prose is a boundary; dots are not (never match an email suffix
    # or silently drop the first label of an address that starts earlier).
    pattern = r"(?<![a-zA-Z0-9_@/.-])(?:https?://)?(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(?::\d+)?(?:[/#?][^\s<>\"'\u4e00-\u9fff，。；（）【】]*)?"
    text = page.get("text", "")
    for match in re.finditer(pattern, text):
        literal = match[0].rstrip(".,;:!)]}")
        url = public_url(literal if literal.startswith(("http://", "https://")) else "https://" + literal)
        if url and url not in refs:
            refs[url] = {"url": url, "text": text[max(0, match.start()-80):match.end()+100],
                         "kind": "text_address"}
    return list(refs.values())


class AgentEvidence:
    def __init__(self, source):
        self.references, self.origins = {}, {}
        for url, label in ((source.career_url, "已核验招聘入口（起点，可能需继续导航）"),
                           (source.official_homepage_url, "公司主页"),
                           (source.hiring_evidence_url, "招聘入口归属依据")):
            if public_url(url):
                self.add(url, label, "registered")

    def add(self, url, text, kind, origin=None, *, snippet=""):
        url = public_url(url)
        if not url:
            return
        now = datetime.now(UTC).isoformat()
        ref = {"url": url, "text": text[:300], "kind": kind, "origin_url": origin,
               "snippet": snippet[:700], "first_seen_at": now, "last_seen_at": now,
               "last_read_at": None, "last_read_status": "unread", "last_result_code": None,
               "seen_in_current_run": True, "read_in_current_run": False}
        # Preserve observed links when a later search repeats the same URL.
        prior = self.references.get(url)
        if not prior or origin:
            self.references[url] = {**(prior or ref), "text": text[:300], "kind": kind, "origin_url": origin}
        ref = self.references[url]
        ref.update(seen_in_current_run=True, last_seen_at=now)
        if snippet:
            ref["snippet"] = snippet[:700]
        if origin:
            self.origins[url] = origin

    def note_result(self, url, result):
        ref = self.references.get(public_url(url))
        if not ref:
            return
        status = result.get("read_status", "failed")
        ref.update(last_read_status=status, last_result_code=result.get("code"))
        if status in {"success", "cached"}:
            ref.update(last_read_at=result.get("read_at") or datetime.now(UTC).isoformat(), read_in_current_run=True)

    def ordered_references(self):
        """Bound memory by execution progress, without guessing which employer/page is valid."""
        def priority(ref):
            if ref["last_read_status"] in {"failed", "not_executed", "unknown"}:
                return 0
            if ref["kind"] == "search" and not ref["last_read_at"]:
                return 1
            if ref["last_read_at"] or ref["kind"] == "registered":
                return 2
            return 3
        recent = sorted(self.references.values(), key=lambda r: r["last_seen_at"] or "", reverse=True)
        return sorted(recent, key=priority)[:MAX_REFERENCES]

    def resume_candidates(self):
        return [ref for ref in self.ordered_references()
                if not ref["read_in_current_run"] and ref["last_read_status"] not in {"success", "cached"}
                and (ref["kind"] != "registered" or ref["last_result_code"])][:40]

    def restore(self, cache):
        """Restore routes, never old page bodies or completed judgments."""
        if "observed_urls" in cache:
            for saved in cache["observed_urls"][:MAX_REFERENCES]:
                self.add(saved.get("url"), saved.get("text", ""), saved.get("kind", "previous_check"),
                         saved.get("origin_url"), snippet=saved.get("snippet", ""))
                ref = self.references.get(public_url(saved.get("url")))
                if ref:
                    for key in ("first_seen_at", "last_seen_at", "last_read_at", "last_read_status", "last_result_code"):
                        if key in saved:
                            ref[key] = saved[key]
                    ref.update(seen_in_current_run=False, read_in_current_run=False)
            return
        # v12 and earlier saved searches and outbound links only inside traces/pages.
        for url in [*cache.get("origins", []), *cache.get("urls", [])]:
            self.add(url, "上轮检查线索，需重新读取", "previous_check")
        for saved in cache.get("pages", {}).values():
            page = {**saved, "links": [HTMLLink(**link) for link in saved.get("links", [])]}
            self.accept(page, page.get("requested_url", page["url"]))
            for url in (page.get("requested_url"), page["url"]):
                if url in self.references:
                    self.references[url].update(last_read_at=page.get("read_at") or page.get("checked_at"),
                                                last_read_status="success")
        for item in cache.get("agent_trace", []):
            if item.get("action") == "search":
                for candidate in item.get("result", {}).get("candidates", []):
                    self.add(candidate.get("url"), candidate.get("title", ""), "search",
                             snippet=candidate.get("snippet", ""))
        for item in cache.get("pending_checks", []):
            self.add(item.get("url"), "上轮未完成读取", "previous_check")
            self.note_result(item.get("url"), {"read_status": "failed", "code": item.get("reason")})
        for ref in self.references.values():
            ref.update(seen_in_current_run=False, read_in_current_run=False)

    def accept(self, page, requested):
        """Keep the requested/final address and outbound links as facts for the agent."""
        final = page["url"]
        parent = requested if final != requested else self.references.get(requested, {}).get("origin_url")
        self.add(final, page.get("title", ""), "read", parent)
        for url in (requested, final):
            self.note_result(url, {"code": "page_read", "read_status": "success",
                                   "read_at": page.get("checked_at")})
        for item in page_references(page):
            self.add(item["url"], item["text"], item["kind"], final)
