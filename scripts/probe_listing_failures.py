"""Inspect bounded public listing reads through the application browser reader."""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["APP_ENV"] = "testing"
from src.services.browser_job_reader import PlaywrightBrowserJobReader
from src.services.recruitment_listing import inspect_listing

OUT = ROOT / "artifacts/company-evidence-repairs-20261019/dynamic-probes"
OUT.mkdir(parents=True, exist_ok=True)
prior = json.loads((ROOT / "artifacts/source-repairs-20261019/entrance-resume/entrances.json").read_text(encoding="utf-8"))["states"]


class Reader(PlaywrightBrowserJobReader):
    @asynccontextmanager
    async def browser_session(self):
        async with super().browser_session() as browser:
            original = browser.new_context

            async def create_context(**kwargs):
                context = await original(**kwargs)
                context.on("page", self.observe)
                return context

            browser.new_context = create_context
            try:
                yield browser
            finally:
                browser.new_context = original

    def observe(self, page):
        page.on("pageerror", lambda error: self.events.append({"kind": "page_error", "message": str(error)[:500]}))
        page.on("requestfailed", lambda req: self.events.append({"kind": "request_failed", "url": req.url, "error": req.failure}))
        page.on("response", lambda res: self.events.append({"kind": "response", "url": res.url, "status": res.status})
                if res.status >= 400 or "/api/" in res.url else None)


async def main():
    reader = Reader(timeout_seconds=12)
    async with reader.reuse():
        for name in ("jd", "xpeng", "bytedance"):
            state = prior[name]
            url = state.get("base") or state["html_queue"][0]["url"]
            reader.events = []
            start = monotonic()
            result = {"url": url}
            try:
                async with asyncio.timeout(35):
                    page = await reader.read_search_listing(url)
                (OUT / f"{name}.html").write_text(page.raw_html, encoding="utf-8")
                caps = inspect_listing(page.raw_html, url=page.final_url)
                result.update(final_url=page.final_url, title=page.title, text=page.visible_text[:6000],
                    api=page.recruitment_api, jobs=[vars(v) for v in caps.jobs], entries=[vars(v) for v in caps.entries],
                    job_controls=caps.job_controls, entry_controls=caps.entry_controls)
            except Exception as error:  # noqa: BLE001 - diagnostics preserve each source's failure
                result.update(error=type(error).__name__, code=getattr(error, "code", None), message=str(error)[:500])
            result.update(seconds=round(monotonic()-start, 2), events=reader.events)
            (OUT / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: v for k,v in result.items() if k not in {"text", "api", "events", "jobs", "entries"}}, ensure_ascii=False), flush=True)


asyncio.run(main())
