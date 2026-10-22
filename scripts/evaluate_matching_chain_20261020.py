"""Frozen, assistant-labelled matching-chain evaluation; synthetic profiles only.

Run prepare before run. Uses the current product runtime, isolated per-JD DBs,
and one recovery pass for incomplete executions. Never changes product data.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "artifacts/matching-chain-live-20261020"
DATASET = ROOT / "artifacts/evaluation/product-jd-development70-v3-human-reviewed-2026-09-07.json"
IDS = [23, 24, 27, 37, 69, 70, 75, 85, 97, 108, 110, 121]
SAFE_SETTINGS = [
    "structured_model_provider", "llm_model", "llm_base_url", "llm_timeout_seconds",
    "llm_reasoning_effort", "llm_response_format", "llm_max_retries",
    "product_parse_mode", "product_parse_run_timeout_seconds", "product_parse_max_model_calls",
    "product_parser_version", "product_prompt_version", "parser_validation_retries",
    "product_parse_transport_retries", "product_parse_retry_backoff_seconds",
    "evidence_matching_mode", "evidence_matching_timeout_seconds",
]


def digest(data):
    if not isinstance(data, bytes):
        data = json.dumps(data, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(data).hexdigest()


def now():
    return datetime.now(UTC).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def append_json(path, value):
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False) + "\n")


def implementation_hashes():
    files = sorted((ROOT / "src").rglob("*.py")) + [Path(__file__)]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p.read_bytes()) for p in files}


def prepare():
    from src.config import get_settings
    from src.domain.education import EducationRecord, validate_education_grounding

    if (OUT / "manifest.json").exists():
        raise SystemExit("Existing frozen manifest: refusing to overwrite")
    source = json.loads(DATASET.read_text(encoding="utf-8"))
    pool = {c["id"]: c for c in source["cases"]}
    evidence = json.loads((ROOT / "datasets/campus_match_candidate_v1.json").read_text(encoding="utf-8"))["evidence"]
    profiles = {}
    for key, name, level, label in [
        ("A", "2027计算机硕士，有课程后端/Agent/RAG项目", "master", "硕士"),
        ("B", "2027计算机专科，同等项目证据但学历不足", "associate", "专科"),
        ("C", "教育资料缺失，保留相同项目证据", None, None),
        ("D", "2027计算机硕士，只有计划而无项目证据", "master", "硕士"),
    ]:
        educations = []
        if level:
            quote = f"虚构测试资料：计算机科学与技术专业，{label}在读，预计2027年毕业。"
            edu = EducationRecord(
                id=f"edu_{key}", level=level, major_raw="计算机科学与技术",
                graduation_year=2027, graduation_source_text="预计2027年毕业",
                graduation_year_kind="expected", status="enrolled",
                source_text=quote, source="synthetic_eval", reviewed=True,
                graduation_year_confirmed=True,
            )
            validate_education_grounding(edu, quote)
            educations = [edu.model_dump(mode="json")]
        records = evidence if key != "D" else [{
            "id": "ev_plans_only", "title": "虚构资料：未实践的计划",
            "claim": "尚无软件开发或产品设计项目经历。Go、Python、React、Kubernetes均为计划学习，目前未实际使用。没有实习、论文、竞赛或开源贡献。",
            "skills": ["Go", "Python", "React", "Kubernetes"], "source": "synthetic_eval",
        }]
        profiles[key] = {
            "name": name, "provenance": "Fictional controlled evaluation, not the user's resume.",
            "profile": {"educations": educations, "education_history_complete": key != "C"},
            "evidence": [{**r, "id": f"{key}_{r['id']}", "user_id": f"eval-{key}"} for r in records],
        }
    positive_a = {23, 37, 70, 75}
    reasons_a = {
        23: "编程、LLM原理、Prompt任选领域，以及比较笔记/组会表达/主动探索有直接材料；不要求顶会或多Agent实践。软能力支持仍有判断空间。",
        24: "已有RAG项目不能证明了解Harness细节、KV Cache、MCP/A2A及多类Agent实现。",
        27: "已有基础与RAG实践，但未证明长文本处理及Fine-Tuning数据工程等完整复合条件。",
        37: "Python项目、RAG实践、学习记录和评测/测试分别支持全部必备条件。",
        69: "具备RAG、LangChain和LoRA，但缺少对齐技术直接证据；顶会是优先而非硬门槛。",
        70: "显式必备仅本科以上；其他技术均写为优先。依当前决策契约为推荐，但不代表胜任SDK职责。",
        75: "计算机硕士、Python工程实践、论文复现学习能力和团队协作均有直接材料。",
        85: "Agent使用和协作有证据，但独立完成产品原型、流程设计和需求文档未获证明。",
        97: "基础与Python有证据，但愿意建设可观测基础设施的具体方向意愿未确认。",
        108: "缺少TypeScript/JavaScript框架、Runtime二次开发、缓存/队列等复合能力证据。",
        110: "NodeJS/Golang/React未实践，计划学习不能代替熟悉；大规模/高并发是优先。",
        121: "缺少分布式系统及资源调度经历；Kubernetes只有学习计划，不能判为已掌握。",
    }
    jobs, cases = [], []
    for n in IDS:
        src = pool[f"campus-ai-{n:03}"]
        jobs.append({k: src[k] for k in ("id", "source", "raw_content", "source_content_sha256")})
        for key in profiles:
            if key == "A":
                decision = "recommended_application" if n in positive_a else "consider"
                reason = reasons_a[n]
            elif key == "B":
                decision, reason = "not_recommended", "完整教育记录仅专科，明确不满足本科/硕士最低学历。"
            elif key == "C":
                decision, reason = "insufficient_information", "学历和毕业年份缺失，应询问而非推定通过或排除。"
            else:
                decision = "recommended_application" if n == 70 else "consider"
                reason = "学历届别符合，但学习计划不能证明必备能力。" if n != 70 else reasons_a[70]
            cases.append({
                "id": f"{src['id']}-{key}", "job_id": src["id"], "profile_key": key,
                "expected_decision": decision,
                "expected_eligibility": {"A": "pass", "B": "fail", "C": "unknown", "D": "pass"}[key],
                "reason": reason,
            })
    settings = get_settings()
    manifest = {
        "version": "matching-chain-controlled-v1", "frozen_at": now(),
        "scope": "Stored public JD original -> current product parser -> qualifications -> semantic experience matching -> build_job_decision",
        "label_status": "assistant_predeclared_controlled_reference_not_independent_human_gold",
        "source_dataset": str(DATASET.relative_to(ROOT)), "source_dataset_sha256": digest(DATASET.read_bytes()),
        "source_split": "previously opened development data; not new held-out generalization data",
        "limitations": [
            "12 selected archived JD snapshots, not a random sample and not a live availability check.",
            "48 candidate/JD pairs share 12 JDs and 4 synthetic profiles; not 48 independent jobs.",
            "Expected labels authored by assistant before predictions; subjective soft-skill boundaries remain.",
            "Tests matching from stored original text, not web discovery, reading, resume import, UI, or hiring outcomes.",
            "Contract recommends when explicit mandatory requirements pass; it does not measure job responsibility fitness.",
        ],
        "protocol": {
            "job_concurrency": 2, "profiles_per_job": 4,
            "parse_cache": "One fresh parse per JD, normally reused by following profiles; cold/warm timings separate.",
            "recovery": "One additional analyze() call only for thrown errors or failed validation rows; keep both attempts. Product-internal retries unchanged.",
            "cache_check": "Repeat completed first-pass analyses and require same analysis ID/decision with zero additional model calls.",
            "metrics": "Exact final-label agreement, 4-class macro-F1 with failures retained, qualification agreement, over-recommendation, false exclusion, mechanical citation grounding, and semantic audit.",
            "false_recommendation": "predicted recommended_application and reference is not recommended_application / all predicted recommended_application",
            "false_exclusion": "predicted not_recommended and reference is not not_recommended / all reference non-exclusions",
            "freeze": "No product changes or reference relabelling after first live call; recovery may change output but initial remains scored.",
        },
        "settings": {k: getattr(settings, k) for k in SAFE_SETTINGS},
        "implementation": implementation_hashes(), "profiles": profiles, "jobs": jobs, "cases": cases,
    }
    write_json(OUT / "manifest.json", manifest)
    (OUT / "manifest.sha256").write_text(digest((OUT / "manifest.json").read_bytes()), encoding="ascii")
    print(json.dumps({"prepared": True, "jobs": len(jobs), "pairs": len(cases), "manifest_sha256": digest((OUT / "manifest.json").read_bytes())}))


class RecordingClient:
    def __init__(self, client, path, meta):
        self.inner, self.path, self.meta = client, path, meta
        self.count = 0

    def __getattr__(self, key):
        return getattr(self.inner, key)

    async def generate(self, request):
        self.count += 1
        start = perf_counter()
        record = {**self.meta, "schema": request.schema_name, "started_at": now(),
                  "request": request.model_dump(mode="json")}
        try:
            response = await self.inner.generate(request)
            record["response"] = response.model_dump(mode="json")
            return response
        except BaseException as error:
            record["error_type"] = type(error).__name__
            record["error_code"] = getattr(error, "code", None)
            raise
        finally:
            record["elapsed_seconds"] = round(perf_counter() - start, 3)
            append_json(self.path, record)


async def run():
    from sqlalchemy import create_engine, event, select
    from sqlalchemy.orm import sessionmaker
    import src.domain
    from src.config import get_settings
    from src.domain.eligibility import EligibilityResult
    from src.domain.matching import RequirementMatch
    from src.domain.models import EvidenceItem
    from src.domain.runs import AgentRun
    from src.infrastructure.database import Base, configure_sqlite_connection
    from src.infrastructure.llm_client import create_structured_model_client
    from src.services.analysis_runtime import create_analysis_service
    from src.services.job_decision import build_job_decision
    from src.services.job_service import JobImportService
    from src.services.profile_service import ProfileService

    manifest_path = OUT / "manifest.json"
    assert digest(manifest_path.read_bytes()) == (OUT / "manifest.sha256").read_text().strip()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert implementation_hashes() == manifest["implementation"], "Code changed since freeze"
    settings = get_settings()
    assert {k: getattr(settings, k) for k in SAFE_SETTINGS} == manifest["settings"], "Config changed since freeze"
    assert settings.structured_model_provider != "fake"
    if (OUT / "run-start.json").exists():
        raise SystemExit("Run already started; do not overwrite raw trials")
    write_json(OUT / "run-start.json", {"started_at": now(), "manifest_sha256": digest(manifest_path.read_bytes())})
    sem = asyncio.Semaphore(manifest["protocol"]["job_concurrency"])
    started = perf_counter()

    async def one_job(job):
        async with sem:
            folder = OUT / job["id"]
            folder.mkdir(exist_ok=True)
            engine = create_engine(f"sqlite:///{(folder / 'runtime.sqlite3').as_posix()}", connect_args={"check_same_thread": False})
            event.listen(engine, "connect", configure_sqlite_connection)
            Base.metadata.create_all(engine)
            Session = sessionmaker(bind=engine, expire_on_commit=False)
            with Session() as session:
                posting = JobImportService(session).import_text(
                    raw_content=job["raw_content"], source_url=job["source"]["source_url"],
                    source_type="manual_text", company=job["source"]["company"], title=job["source"]["title"],
                )
                posting_id = posting.id
                for key, p in manifest["profiles"].items():
                    ProfileService(session).upsert(f"eval-{key}", p["profile"])
                    for raw in p["evidence"]:
                        session.add(EvidenceItem(**raw, type="project"))
                    session.commit()
            cases = [c for c in manifest["cases"] if c["job_id"] == job["id"]]

            async def execute(case, attempt):
                clients = []
                meta = {"case_id": case["id"], "attempt": attempt}

                def factory(config):
                    client = RecordingClient(create_structured_model_client(config), folder / "calls.jsonl", meta)
                    clients.append(client)
                    return client

                begin = perf_counter()
                row = {**meta, "started_at": now(), "job_id": job["id"], "profile_key": case["profile_key"]}
                with Session() as session:
                    service = create_analysis_service(session, settings=settings, client_factory=factory)
                    try:
                        result = await service.analyze(user_id=f"eval-{case['profile_key']}", job_id=posting_id)
                        analysis = result.analysis
                        decision = build_job_decision(
                            eligibility=EligibilityResult.model_validate(analysis.eligibility),
                            matches=[RequirementMatch.model_validate(m) for m in analysis.matches],
                        ).model_dump(mode="json")
                        row.update({
                            "status": "completed" if all(m.get("validation_status") == "passed" for m in analysis.matches) else "incomplete",
                            "analysis_id": analysis.id, "decision": decision, "eligibility": analysis.eligibility,
                            "matches": analysis.matches, "structured_jd": analysis.structured_jd,
                            "parse_result_id": result.parse_result.id, "parser_version": result.parse_result.parser_version,
                        })
                        runs = [session.get(AgentRun, rid) for rid in result.agent_run_ids if rid]
                        row["runs"] = [{"id": r.id, "type": r.run_type, "status": r.status,
                                        "validation": r.validation_result, "duration_ms": r.duration_ms} for r in runs]
                        row["cold_parse"] = any(r.run_type == "jd_parse" and not (r.validation_result or {}).get("cache_hit") for r in runs)
                    except Exception as error:
                        session.rollback()
                        row.update({"status": "error", "error_type": type(error).__name__,
                                    "error_code": getattr(error, "code", None), "stage": getattr(error, "stage", None),
                                    "agent_run_id": getattr(error, "agent_run_id", None)})
                    row["elapsed_seconds"] = round(perf_counter() - begin, 3)
                    row["model_calls"] = sum(c.count for c in clients)
                    if row["status"] == "completed" and attempt == 1:
                        before = row["model_calls"]
                        cache_start = perf_counter()
                        cached = await service.analyze(user_id=f"eval-{case['profile_key']}", job_id=posting_id)
                        cached_decision = build_job_decision(
                            eligibility=EligibilityResult.model_validate(cached.analysis.eligibility),
                            matches=[RequirementMatch.model_validate(m) for m in cached.analysis.matches],
                        ).model_dump(mode="json")
                        row["cache_check"] = {
                            "same_analysis": cached.analysis.id == row["analysis_id"],
                            "same_decision": cached_decision == row["decision"],
                            "extra_calls": sum(c.count for c in clients) - before,
                            "elapsed_seconds": round(perf_counter() - cache_start, 3),
                        }
                write_json(folder / f"{case['profile_key']}-attempt{attempt}.json", row)
                append_json(OUT / "progress.jsonl", {k: row[k] for k in ("case_id", "attempt", "status", "elapsed_seconds", "model_calls")})
                print(json.dumps({"case": case["id"], "attempt": attempt, "status": row["status"],
                                  "decision": row.get("decision", {}).get("recommendation"), "seconds": row["elapsed_seconds"]}), flush=True)
                return row

            retries = []
            for case in cases:
                row = await execute(case, 1)
                if row["status"] != "completed":
                    retries.append(case)
            for case in retries:
                await execute(case, 2)
            engine.dispose()

    outcomes = await asyncio.gather(*(one_job(j) for j in manifest["jobs"]), return_exceptions=True)
    errors = [{"job_id": job["id"], "type": type(result).__name__, "message": str(result)[:400]} for job, result in zip(manifest["jobs"], outcomes) if isinstance(result, BaseException)]
    write_json(OUT / "run-end.json", {"finished_at": now(), "elapsed_seconds": round(perf_counter() - started, 3), "worker_errors": errors,
                                    "implementation_unchanged": implementation_hashes() == manifest["implementation"]})
    print(json.dumps({"finished": True, "seconds": round(perf_counter() - started, 1), "worker_errors": errors}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["prepare", "run"])
    args = parser.parse_args()
    if args.action == "prepare":
        prepare()
    else:
        asyncio.run(run())
