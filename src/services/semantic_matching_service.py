"""Persist opt-in batch matching and reuse only valid, identical inputs."""

import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select

from src.domain.matching import RequirementMatch
from src.domain.runs import AgentRun, generate_agent_run_id
from src.services.semantic_evidence_matcher import PROMPT_VERSION


async def match_with_cache(
    session, *, matcher, user_id, job_id, requirements, evidence
):
    payload = {
        "user_id": user_id,
        "matcher": matcher.identity(),
        "requirements": [r.model_dump(mode="json") for r in requirements],
        "evidence": [
            r.model_dump(mode="json") for r in evidence if r.user_id == user_id
        ],
    }
    input_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    cached = session.scalar(
        select(AgentRun)
        .where(
            AgentRun.user_id == user_id,
            AgentRun.target_id == job_id,
            AgentRun.target_type == "job_ordinary_requirements",
            AgentRun.run_type == "evidence_match",
            AgentRun.input_hash == input_hash,
            AgentRun.status == "succeeded",
            AgentRun.validation_status == "passed",
        )
        .order_by(AgentRun.created_at.desc())
    )
    if cached:
        return [
            RequirementMatch.model_validate(m) for m in cached.output["matches"]
        ], cached.id
    run = AgentRun(
        id=generate_agent_run_id(),
        user_id=user_id,
        run_type="evidence_match",
        target_type="job_ordinary_requirements",
        target_id=job_id,
        input_hash=input_hash,
        model=matcher.client.model_name,
        prompt_version=PROMPT_VERSION,
        status="failed",
        validation_status="failed",
        started_at=datetime.now(UTC),
    )
    session.add(run)
    session.commit()
    execution = await matcher.match(
        user_id=user_id,
        requirements=requirements,
        evidence=evidence,
    )
    valid = not execution.error_code and not execution.validation_issues
    run.status = "succeeded" if valid else "failed"
    run.validation_status = "passed" if valid else "failed"
    run.output = {
        "matches": [m.model_dump(mode="json") for m in execution.matches],
        "raw_output": execution.raw_output,
    }
    run.validation_result = {
        "model_call_count": execution.call_count,
        "usage": execution.usage,
        "issues": execution.validation_issues,
        "code": execution.error_code,
        **execution.response_metadata,
    }
    run.error = execution.error_code
    run.duration_ms = execution.duration_ms
    run.finished_at = datetime.now(UTC)
    session.commit()
    return execution.matches, run.id
