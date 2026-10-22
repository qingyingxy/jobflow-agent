"""Audit the isolated two-goal trial without changing product decisions."""

import argparse
import json
import os
import sys
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PRIMARY = "goal_510142e137774f3ea1f7"
ALTERNATE = "goal_e34b3c1d59e84092ac86"
CASES = {
    "job_f317df23c43e462182a8": (
        "recommended",
        "深圳、27届校招、后端研发均明确；Java是接受的语言之一，Go/C++项目经验只是优先项。曾推荐后又待核实，是判断被旧目标覆盖，不是原文缺失。",
    ),
    "job_a57fba9d38b24de3b42b": (
        "recommended",
        "杭州、2027校招、Java平台开发有直接证据；数据平台/调度系统属于后端，具体技术及项目要求仍需本人核对。",
    ),
    "job_12950872428b4c01a828": (
        "recommended",
        "杭州、2027校招、基础后端明确，Python或Java至少一门；可以推荐，但属于AIOps后端，并非仅使用Java的岗位。",
    ),
    "job_df6d3f5e855f4016adca": (
        "excluded",
        "商汤后端开发岗位接受Java及2027届，但唯一地点为北京，与杭州/深圳明确冲突。",
    ),
    "job_361d9bdbdae643cb9e0e": (
        "pending",
        "深圳、2027届、全栈后端成立，但语言写的是Golang/Python/Node.js，没有Java证据，不能当作已确认的Java岗位。",
    ),
    "job_e336e38649094f9bae1e": (
        "pending",
        "DeepSeek服务端欢迎应届生且部分岗位可选杭州，但未写2027届及Java；需保留不确定性。",
    ),
    "job_03f0a65b751b4a7ba9da": (
        "invalid_detail",
        "华为页面仍是{{model.jobArea}}、{{model.mainBusiness}}模板占位符；What We Offer不是岗位名。不应把它当已读到的有效岗位正文，应该留在页面读取队列。AI未错误推荐，但前序入库质量有问题。",
    ),
}


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    folder = args.folder.resolve()
    if not folder.is_relative_to(ROOT / "artifacts"):
        parser.error("Only isolated artifact databases are supported")
    os.environ["DATABASE_URL"] = "sqlite:///" + (folder / "trial.db").as_posix()
    os.environ["APP_ENV"] = "testing"
    from sqlalchemy import select, text

    from src.domain.job import JobPosting
    from src.infrastructure.database import SessionLocal
    from src.services.search_goal_service import SearchGoalService

    # SQLite itself enforces read-only behavior for this audit connection.
    with SessionLocal() as session:
        session.execute(text("PRAGMA query_only=ON"))
        libraries = {goal: SearchGoalService(session).library("local-user", goal, include_progress=False)
                     for goal in (PRIMARY, ALTERNATE)}
        postings = {j.id: j for j in session.scalars(select(JobPosting))}
        alternate = {m["job_posting_id"]: m for m in libraries[ALTERNATE]["result_matches"]}
        cases = [{"id": identifier, "title": postings[identifier].title,
                  "url": postings[identifier].source_url,
                  "raw_content": postings[identifier].raw_content,
                  "expected": expected, "finding": finding,
                  "observed": alternate.get(identifier)}
                 for identifier, (expected, finding) in CASES.items() if identifier in postings]
    save(folder / "cross-goal-final.json", libraries)
    save(folder / "audit.json", cases)
    events = [json.loads(line) for line in (folder / "decision-history.jsonl").read_text(encoding="utf-8").splitlines()]
    histories = defaultdict(list)
    for event in events:
        for change in event["changes"]:
            if change["previous_goal"] in (PRIMARY, ALTERNATE) and change["current_goal"] in (PRIMARY, ALTERNATE) and change["previous_goal"] != change["current_goal"]:
                histories[change["id"]].append({"at": event["at"], **change})
    oscillating = []
    for identifier, history in histories.items():
        if any(first["previous_goal"] == second["current_goal"] and first["body_hash"] == second["body_hash"]
               for first, second in pairwise(history)):
            oscillating.append(identifier)
    timeline = []
    for path in sorted(folder.glob("visit-*/*.json")):
        if not (path.name in ("before.json", "after.json", "idle-start.json") or path.name.startswith("after-round-")):
            continue
        snapshot = read(path)
        timeline.append({"at": snapshot["at"], "snapshot": str(path.relative_to(folder)),
                         "counts": snapshot["library"]["counts"],
                         "cases": {m["job_posting_id"]: m["review_status"] for m in snapshot["library"]["result_matches"] if m["job_posting_id"] in CASES}})
    baseline = read(folder.parent / "primary/latest.json")
    previous = {m["job_posting_id"] for m in baseline["library"]["result_matches"] if m["review_status"] == "recommended"}
    now = {m["job_posting_id"]: m for m in libraries[PRIMARY]["result_matches"]}
    lost = [{"id": identifier, "title": postings[identifier].title,
             "current_status": now[identifier]["review_status"], "checks": now[identifier]["checks"]}
            for identifier in sorted(previous) if now[identifier]["review_status"] != "recommended"]
    result = {"monitor_samples": len(events), "first_at": events[0]["at"], "last_at": events[-1]["at"],
              "cross_goal_overwrites": sum(map(len, histories.values())),
              "jobs_overwritten": len(histories), "same_body_round_trip_jobs": oscillating,
              "histories": histories, "timeline": sorted(timeline, key=lambda x: x["at"]),
              "primary_previously_recommended_now_changed": lost,
              "final_counts": {goal: library["counts"] for goal, library in libraries.items()},
              "interpretation": "Condition fingerprints reject another goal's judgment, so this demonstrates discarded per-goal work and repeated AI analysis, not evidence of presenting the other goal's conclusion as valid."}
    save(folder / "multi-goal-audit.json", result)
    print(json.dumps({key: result[key] for key in ("cross_goal_overwrites", "jobs_overwritten", "same_body_round_trip_jobs", "final_counts")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
