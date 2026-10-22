"""Inspect the public structured output for one long saved job, without writes."""
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/quality-pipeline-20261019"
os.environ["DATABASE_URL"] = "sqlite:///" + (OUT / "final-acceptance/trial.db").as_posix()
os.environ["APP_ENV"] = "testing"


async def main():
    from src.config import get_settings
    from src.domain.job import JobPosting
    from src.infrastructure.database import SessionLocal
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.search_goal_service import posting_stub
    from src.services.source_understanding import SourceUnderstanding

    baseline = json.loads((ROOT / "artifacts/job-acceptance-20261019/results.json").read_text(encoding="utf-8"))
    row = baseline["results"][1]
    records = []
    settings = get_settings().model_copy(update={"llm_timeout_seconds": 30, "llm_max_retries": 0,
        "web_search_semantic_timeout_seconds": 30})
    delegate = create_structured_model_client(settings)
    class Recorder:
        async def generate(self, request):
            response = await delegate.generate(request)
            records.append({"output": response.output})
            return response
    with SessionLocal() as session:
        stub = posting_stub(session.get(JobPosting, row["job_id"]))
    from dataclasses import replace
    stub = replace(stub, recruitment_context={k: v for k, v in stub.recruitment_context.items()
        if k not in {"source_understanding", "source_review_attempt"}})
    runtime = SourceUnderstanding(settings, client=Recorder(),
        on_event=lambda kind, data: records.append({"kind": kind, **data}))
    result = await runtime.review(stub, query=baseline["query"], conditions=baseline["conditions"])
    records.append({"attempt": result.recruitment_context.get("source_review_attempt")})
    (OUT / "long-body-output.json").write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(records[-1])


if __name__ == "__main__":
    asyncio.run(main())
