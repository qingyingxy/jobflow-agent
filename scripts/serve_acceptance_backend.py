"""Real FastAPI/SQLite server, with optional external HTTP fixtures for E2E.

Only this test launcher substitutes the model and recruiting-site origins.
No JobFlow API response is mocked. Without --fixture, serves a live acceptance DB.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

COHORT = "2027届中国大陆毕业生，2026届海外毕业生"
REQUIREMENT = "熟悉 Python 或 Java 中至少一种语言"
RAW = f"验收公司招聘 Python 开发工程师，工作地点北京。{COHORT}。本科及以上学历。{REQUIREMENT}。负责开发软件。"


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/fixture/jobs/"):
            city = "上海" if self.path.endswith("shanghai") else "北京"
            title = f"Python 开发工程师（{city}）"
            text = f"招聘类型：校园招聘。岗位职责：负责后端 Python 服务开发。任职要求：{COHORT}。本科及以上学历。{REQUIREMENT}。"
            structured = {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "title": title,
                "description": text,
                "hiringOrganization": {"name": "链路验收公司"},
                "jobLocation": {"address": {"addressLocality": city}},
                "employmentType": "FULL_TIME",
            }
            body = (
                f'<html><head><title>{title}</title><script type="application/ld+json">'
                + json.dumps(structured, ensure_ascii=False)
                + f"</script></head><body><h1>{title}</h1><p>工作地点：{city}。</p>"
                + f'<p>校园招聘</p><p>{text}</p><a href="/apply">申请职位</a></body></html>'
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        job = {
            "id": 1001,
            "title": "Python 开发工程师",
            "location": {"name": "北京"},
            "absolute_url": "https://boards.greenhouse.io/jobflowfixture/jobs/1001",
            "content": f"<h1>Python 开发工程师</h1><p>{RAW}</p>",
        }
        path = urlsplit(self.path).path
        if path == "/v1/boards/jobflowfixture/jobs":
            return self.respond({"jobs": [job]})
        if path == "/v1/boards/jobflowfixture/jobs/1001":
            return self.respond(job)
        return self.respond({"error": "fixture not found"}, 404)

    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path.endswith("/responses"):
            return self.respond(
                {
                    "status": "completed",
                    "output": [
                        {
                            "type": "web_search_call",
                            "status": "completed",
                            "action": {"query": request["input"]},
                        },
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "[Python 开发工程师（上海）](https://careers.fixture.example/jobs/shanghai)\n"
                                    "[Python 开发工程师（北京）](https://careers.fixture.example/jobs/beijing)",
                                }
                            ],
                        },
                    ],
                }
            )
        schema = request.get("response_format", {}).get("json_schema", {}).get("name")
        if schema == "product_job_extraction":
            prompt = " ".join(
                m["content"] for m in request["messages"] if m["role"] == "user"
            )
            city = "上海" if "上海" in prompt else "北京"
            output = {
                "facts": {
                    "graduation_years": {"values": [2026, 2027], "source_text": COHORT},
                    "locations": {"values": [city], "source_text": city},
                    "education_requirements": {
                        "values": ["本科及以上"],
                        "source_text": "本科及以上学历",
                    },
                },
                "requirements": [{"source_text": REQUIREMENT, "level": "required"}],
                "responsibilities": [
                    "负责后端 Python 服务开发"
                    if "负责后端 Python 服务开发" in prompt
                    else "负责开发软件"
                ],
            }
        elif schema == "product_requirement_relations":
            output = {
                "decisions": [
                    {
                        "requirement_index": 0,
                        "relation": "any_of",
                        "items": ["Python", "Java"],
                        "reason": "明确任选一种",
                    }
                ]
            }
        elif schema == "campus_semantic_matches":
            payload = json.loads(
                next(m["content"] for m in request["messages"] if m["role"] == "user")
            )
            # Deterministic external-model fixture for synthetic Python evidence.
            citations = [
                s["id"]
                for e in payload["evidence"]
                for s in e["sentences"]
                if "Python" in s["text"]
            ]
            output = {
                "judgments": [
                    {
                        "requirement_index": r["requirement_index"],
                        "support_level": "supported"
                        if citations
                        else "needs_confirmation",
                        "explanation": "Python 服务开发经历支持语言要求。"
                        if citations
                        else "暂无证据。",
                        "citations": citations,
                        "missing": [],
                    }
                    for r in payload["requirements"]
                ]
            }
        else:
            return self.respond({"error": "unexpected model request"}, 422)
        return self.respond(
            {
                "id": "fixture-model-response",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(output, ensure_ascii=False),
                        },
                    }
                ],
            }
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument(
        "--fixture-semantic",
        action="store_true",
        help="Use semantic matching only against the local fixture server",
    )
    parser.add_argument("--database", type=Path)
    parser.add_argument("--port", type=int, default=18021)
    parser.add_argument("--fixture-port", type=int, default=18022)
    args = parser.parse_args()
    if args.fixture_semantic and not args.fixture:
        parser.error("--fixture-semantic requires --fixture")
    temporary = (
        tempfile.TemporaryDirectory(prefix="jobflow-e2e-") if args.fixture else None
    )
    database = Path(temporary.name) / "e2e.db" if temporary else args.database
    if database is None or (not args.fixture and not database.is_file()):
        parser.error("Supply an existing --database or use --fixture")
    os.environ.update(
        DATABASE_URL=f"sqlite:///{database.resolve().as_posix()}",
        FRONTEND_ORIGINS="http://localhost:3001,http://127.0.0.1:3001",
        LOG_LEVEL="WARNING",
        AUTH_MODE="local",
        ALLOW_INSECURE_USER_HEADER="true",
    )
    fixture_server = None
    if args.fixture:
        os.environ.update(
            STRUCTURED_MODEL_PROVIDER="openai_compatible",
            LLM_BASE_URL=f"http://127.0.0.1:{args.fixture_port}/v1",
            LLM_API_KEY="fixture-only",
            LLM_MODEL="fixture-external-model",
            LLM_RESPONSE_FORMAT="json_schema",
            LLM_THINKING_MODE="auto",
            LLM_REASONING_EFFORT="auto",
            URL_FETCH_PROXY="",
            PRIVATE_STORAGE_DIR=str(Path(temporary.name) / "private"),
            EVIDENCE_MATCHING_MODE="semantic" if args.fixture_semantic else "local",
            WEB_SEARCH_PROVIDER="responses",
            WEB_SEARCH_DECISION_MODE="rule",
            WEB_SEARCH_MAX_ROUNDS="1",
            WEB_SEARCH_TARGET_JOBS="2",
            WEB_SEARCH_BUDGET_SECONDS="15",
        )
        fixture_server = ThreadingHTTPServer(
            ("127.0.0.1", args.fixture_port), FixtureHandler
        )
        threading.Thread(target=fixture_server.serve_forever, daemon=True).start()

    import httpx
    import uvicorn

    from src.api import discovery
    from src.infrastructure.database import Base, engine
    from src.main import app
    from src.services.discovery_sources import GreenhouseAdapter
    from src.services.url_reader import FetchedResponse

    if args.fixture:

        class ExternalFixtureReader:
            async def fetch(self, url):
                parsed = urlsplit(url)
                if parsed.hostname != "careers.fixture.example" or parsed.path not in {
                    "/jobs/shanghai",
                    "/jobs/beijing",
                }:
                    raise ValueError("Unexpected external page URL")
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(
                        f"http://127.0.0.1:{args.fixture_port}/fixture{parsed.path}"
                    )
                    response.raise_for_status()
                    return FetchedResponse(
                        url, url, response.status_code, "text/html", response.content
                    )

            async def fetch_json(self, url):
                parsed = urlsplit(url)
                if (
                    parsed.hostname != "boards-api.greenhouse.io"
                    or not parsed.path.startswith("/v1/boards/jobflowfixture/jobs")
                ):
                    raise ValueError("Unexpected external fixture URL")
                async with httpx.AsyncClient(trust_env=False) as client:
                    response = await client.get(
                        f"http://127.0.0.1:{args.fixture_port}{parsed.path}"
                    )
                    response.raise_for_status()
                    return FetchedResponse(
                        url,
                        url,
                        response.status_code,
                        "application/json",
                        response.content,
                    ), response.json()

        def fixture_adapter(source_url, *, company=None):
            return GreenhouseAdapter.from_board_url(
                source_url, company=company, reader=ExternalFixtureReader(), max_jobs=3
            )

        discovery.create_greenhouse_adapter = fixture_adapter
        from src.services import multiround_search, web_search_service
        from src.services.responses_search import ResponsesSearchProvider

        def fixture_search(query, company_ids=None):
            return ResponsesSearchProvider(
                query=query,
                base_url=f"http://127.0.0.1:{args.fixture_port}/v1",
                api_key="fixture-only",
                model="fixture-external-model",
            )

        discovery.create_web_search_provider = fixture_search
        web_search_service.create_web_search_provider = fixture_search
        multiround_search.enabled_company_source_hosts = lambda: {
            "careers.fixture.example"
        }
        multiround_search.enabled_company_sources = lambda *args: []
        multiround_search.SafeHTTPReader = lambda **kwargs: ExternalFixtureReader()
        Base.metadata.create_all(engine)
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        engine.dispose()
        if fixture_server:
            fixture_server.shutdown()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    main()
