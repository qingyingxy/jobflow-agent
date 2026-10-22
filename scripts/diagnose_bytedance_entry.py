"""Compare observed ByteDance entry URLs, redirects, raw hrefs and browser DOM."""
import asyncio
import json
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/job-acceptance-20261019/bytedance"


class Links(HTMLParser):
    def __init__(self, base):
        super().__init__()
        self.base, self.bases, self.links = base, [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "base":
            self.bases.append(attrs)
        if tag == "a" and attrs.get("href"):
            self.links.append({"href": attrs["href"], "resolved": urljoin(self.base, attrs["href"])})


async def main():
    from src.config import get_settings
    from src.services.browser_job_reader import PlaywrightBrowserJobReader
    from src.services.recruitment_listing import inspect_listing
    from src.services.url_reader import SafeHTTPReader

    OUT.mkdir(parents=True, exist_ok=False)
    settings = get_settings()
    urls = ["https://jobs.bytedance.com/campus/", "https://jobs.bytedance.com/experienced",
            "https://jobs.bytedance.com/position", "https://jobs.bytedance.com/en",
            "https://jobs.bytedance.com/campus/position/7667885791859837237/detail"]
    http = SafeHTTPReader(proxy=settings.url_fetch_proxy, max_retries=0, timeout_seconds=15,
        proxy_allowed_hosts={"jobs.bytedance.com", "joinbytedance.com"},
        proxy_allow_unlisted_hosts=settings.url_fetch_proxy_allow_unlisted_hosts)
    browser = PlaywrightBrowserJobReader(timeout_seconds=15)
    results = []
    async with browser.reuse():
        for index, url in enumerate(urls, 1):
            result = {"url": url}
            for mode in ("http", "browser"):
                try:
                    async with asyncio.timeout(45):
                        if mode == "http":
                            response = await http.fetch(url)
                            raw, final = response.body.decode("utf-8", errors="replace"), response.final_url
                            value = {"status": response.status_code, "redirects": response.redirect_chain}
                        else:
                            response = await browser.read_search_listing(url)
                            raw, final = response.raw_html, response.final_url
                            value = {"title": response.title, "text": response.visible_text,
                                     "redirects": response.redirect_chain, "api": response.recruitment_api}
                        (OUT / f"{index}-{mode}.html").write_text(raw, encoding="utf-8")
                        parser = Links(final)
                        parser.feed(raw)
                        caps = inspect_listing(raw, url=final)
                        value.update(final_url=final, bases=parser.bases, links=parser.links,
                            entries=[vars(e) for e in caps.entries], jobs=[vars(j) for j in caps.jobs])
                        result[mode] = value
                except Exception as error:  # noqa: BLE001 - preserve bounded diagnostics
                    result[mode] = {"error": type(error).__name__, "code": getattr(error, "code", None), "message": str(error)}
            results.append(result)
            (OUT / "diagnosis.json").write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
            print(json.dumps({"url": url, **{m: {k: v for k, v in result[m].items()
                if k in {"status", "title", "final_url", "redirects", "error", "code", "message"}} for m in ("http", "browser")}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
