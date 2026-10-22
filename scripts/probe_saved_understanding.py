"""Record public-page model outputs to diagnose failed page contracts."""
import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def main():
    from src.config import get_settings
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.job_detail_scope import readable_page_text
    from src.services.source_understanding import SourceUnderstanding
    from src.services.url_reader import parse_html_document

    source = ROOT / "artifacts/job-acceptance-20261019"
    output = ROOT / "artifacts/quality-pipeline-20261019"
    output.mkdir(exist_ok=True)
    cohort = json.loads((source / "results.json").read_text(encoding="utf-8"))
    settings = get_settings().model_copy(update={"llm_timeout_seconds": 30, "llm_max_retries": 0,
        "web_search_semantic_timeout_seconds": 30})

    async def check(index):
        row = next(r for r in cohort["results"] if r["index"] == index)
        records = []
        delegate = create_structured_model_client(settings)

        class RecordingClient:
            async def generate(self, request):
                response = await delegate.generate(request)
                records.append({"schema": request.schema_name, "output": response.output})
                return response

        runtime = SourceUnderstanding(settings, client=RecordingClient(), query=cohort["query"], conditions=cohort["conditions"],
            on_event=lambda kind, data: records.append({"event": kind, **data}))
        raw = (source / f"{index:02d}/page.html").read_text(encoding="utf-8")
        document = replace(parse_html_document(raw), text=readable_page_text(raw))
        analyzed = await runtime.analyze_page(document, url=row["url"], title_hint=row["title"][:200])
        records.append({"accepted": analyzed is not None, "text": document.text})
        (output / f"probe-{index:02d}.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps({"index": index, "accepted": analyzed is not None}, ensure_ascii=False), flush=True)

    await asyncio.gather(check(2), check(25))


if __name__ == "__main__":
    asyncio.run(main())
