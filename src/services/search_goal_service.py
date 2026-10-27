"""User-owned goals and a current, deduplicated view of saved jobs."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from src.domain.application import CandidateJob
from src.domain.discovery import DiscoveryRun, JobLead
from src.domain.job import JobPosting
from src.domain.search_goal import SearchGoal, SearchGoalConditions
from src.services.discovery_matching import (
    apply_posting_availability,
    classify_discovery_job,
)
from src.services.discovery_sources import JobStub
from src.services.job_role_review import load_role_review
from src.services.lead_providers import LeadCandidate, LeadProviderKind
from src.services.search_intent import (
    INTENT_VERSION,
    conditions_query,
    parse_conditions,
    repair_occupation_suffix,
)


def posting_stub(job):
    return JobStub(
        source_id=job.source_id or "saved",
        source_job_id=job.source_job_id or job.id,
        title=job.title,
        company=job.company,
        locations=job.locations or [],
        job_type=job.job_type,
        published_at=job.published_at,
        raw_content=job.raw_content,
        recruitment_context=job.recruitment_context or {},
        detail_url=job.source_url or "",
    )


def utc_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value


class SearchGoalService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, user_id, goal_id):
        goal = self.session.get(SearchGoal, goal_id)
        if goal is None or goal.user_id != user_id:
            raise LookupError("求职目标不存在")
        self._upgrade_local_scope(goal)
        return goal

    def list(self, user_id):
        goals = list(
            self.session.scalars(
                select(SearchGoal)
                .where(SearchGoal.user_id == user_id)
                .order_by(SearchGoal.updated_at.desc(), SearchGoal.id.desc())
            )
        )
        for goal in goals:
            self._upgrade_local_scope(goal)
        return goals

    def _upgrade_local_scope(self, goal):
        """Repair legacy alias loss only when provenance proves local parsing.

        Manually edited/semantic conditions and active run snapshots are never
        rewritten. Changed semantics get a new version and invalidate old reviews.
        """
        origins = goal.condition_sources or {}
        old = SearchGoalConditions.model_validate(goal.conditions)
        repaired = repair_occupation_suffix(goal.input_text, old, origins)
        if repaired is None and (origins.get("_intent_version") or origins.get("roles") != "本次输入"):
            return
        if self.session.scalar(select(DiscoveryRun.id).where(
            DiscoveryRun.search_goal_id == goal.id, DiscoveryRun.status == "RUNNING",
        ).limit(1)):
            return
        if repaired is not None:
            self._apply_scope_upgrade(goal, repaired, {**origins,
                "keywords": "本次输入（已合并通用职业后缀）"})
            return
        from src.services.search_constraints import select_term_groups
        from src.services.search_vocabulary import _ROLE_GROUPS

        parsed = parse_conditions(goal.input_text)
        heads, _ = select_term_groups(
            "、".join([*parsed.roles, *parsed.preferred_roles]), [g[0] for g in _ROLE_GROUPS]
        )
        if set(old.roles) != {g[0] for g in heads}:
            return
        if old.roles == parsed.roles and old.preferred_roles == parsed.preferred_roles:
            return
        upgraded = old.model_copy(update={
            "roles": parsed.roles, "preferred_roles": parsed.preferred_roles,
        })
        self._apply_scope_upgrade(goal, upgraded, {**origins, "roles": "本次输入（已恢复原文方向限定）"})

    def _apply_scope_upgrade(self, goal, upgraded, origins):
        previous_version = goal.version
        result = self.session.execute(update(SearchGoal).where(
            SearchGoal.id == goal.id, SearchGoal.version == previous_version,
        ).values(
            conditions=upgraded.model_dump(), query=conditions_query(upgraded),
            version=previous_version + 1,
            condition_sources={**origins, "_intent_version": INTENT_VERSION},
            updated_at=datetime.now(UTC),
        ), execution_options={"synchronize_session": False})
        if result.rowcount:
            self.session.commit()
        self.session.refresh(goal)

    def save(
        self,
        *,
        user_id,
        input_text,
        conditions,
        condition_sources,
        name=None,
        company_ids=None,
        goal_id=None,
        expected_version=None,
    ):
        from src.services.company_registry import enabled_company_sources

        enabled_company_sources(company_ids or None, session=self.session, user_id=user_id)
        query = conditions_query(conditions)
        if not query or len(query) > 2000:
            raise ValueError(
                "请填写岗位方向、地点或其他搜索条件，整理后的条件不能超过2000个字符"
            )
        if goal_id:
            goal = self.get(user_id, goal_id)
            if expected_version != goal.version:
                raise RuntimeError("目标已在其他页面修改，请刷新后再保存")
        else:
            # Retrying an initial save does not duplicate identical goals.
            goal = next(
                (
                    g
                    for g in self.list(user_id)
                    if g.query == query and g.company_ids == company_ids
                ),
                None,
            )
            if goal is None:
                goal = SearchGoal(user_id=user_id, version=1)
                self.session.add(goal)
        previous_version = goal.version
        next_version = previous_version + int(
            bool(goal.query)
            and (goal.query != query or goal.company_ids != company_ids)
        )
        goal_name = (
            name
            or " ".join(
                [
                    *(str(y) + "届" for y in conditions.graduation_years),
                    *conditions.locations,
                    *conditions.preferred_locations,
                    *conditions.roles,
                    *conditions.keywords,
                    *conditions.job_types,
                ]
            )[:100]
            or input_text[:100]
        )
        values = {
            "name": goal_name,
            "input_text": input_text,
            "query": query,
            "conditions": conditions.model_dump(),
            "condition_sources": {**condition_sources, "_intent_version": INTENT_VERSION},
            "company_ids": company_ids,
            "version": next_version,
            "updated_at": datetime.now(UTC),
        }
        if goal_id:
            result = self.session.execute(
                update(SearchGoal)
                .where(
                    SearchGoal.id == goal.id,
                    SearchGoal.user_id == user_id,
                    SearchGoal.version == expected_version,
                )
                .values(**values),
                execution_options={"synchronize_session": False},
            )
            if result.rowcount != 1:
                self.session.rollback()
                raise RuntimeError("目标已在其他页面修改，请刷新后再保存")
        else:
            for key, value in values.items():
                setattr(goal, key, value)
        self.session.commit()
        self.session.refresh(goal)
        return goal

    def postings(self, user_id):
        from src.services.job_identity import unique_candidates

        return [job for _, job in unique_candidates(self.session, user_id)]

    def snapshot(self, user_id, query=None):
        result = {}
        for job in self.postings(user_id):
            stub = posting_stub(job)
            match = apply_posting_availability(
                classify_discovery_job(stub, query=query, role_review=load_role_review(
                    self.session, user_id=user_id, job=stub, query=query)), job
            )
            result[job.id] = {
                "content_hash": job.content_hash,
                "availability_status": job.availability_status,
                "filter_status": match.filter_status,
                "review_status": match.review_status,
            }
        return result

    def refresh_candidates(self, user_id, *, query, conditions, limit=8,
                           company_id=None, source_group=None, primary=None, include_body_reviews=True,
                           company_sources=None):
        """Recheck stale sources and resume unresolved reviews on fresh evidence."""
        now = datetime.now(UTC)
        result = []
        if limit <= 0:
            return result
        from src.config import get_settings
        from src.services.source_understanding import (
            pending_review_fields,
            review_attempt,
        )

        settings = get_settings()
        if primary is None:
            primary = (settings.web_search_semantic_enabled and settings.web_search_understanding_mode == "ai"
                       and settings.structured_model_provider != "fake")

        from src.services.search_scheduling import listing_priority

        company_counts, queued = {}, []
        ignored = set(self.session.scalars(select(CandidateJob.job_posting_id).where(
            CandidateJob.user_id == user_id, CandidateJob.status == "IGNORED")))
        for job in self.postings(user_id):
            from src.services.company_scope import in_company_scope

            if not in_company_scope(job, company_sources):
                continue
            from urllib.parse import urlsplit

            group = source_group(job.source_url or "", job.company) if source_group else (job.company or urlsplit(job.source_url or "").hostname)
            if company_id and group != company_id:
                continue
            verified = utc_time(job.last_verified_at)
            stale = not verified or now - verified > timedelta(days=7)
            uncertain = (job.verification_status != "VERIFIED_OFFICIAL"
                         or job.availability_status == "STALE"
                         or (job.availability_status == "UNKNOWN"
                             and (not verified or now - verified >= timedelta(days=1))))
            if (
                not job.source_url
                or job.availability_status == "CLOSED"
                or job.id in ignored
            ):
                continue
            stub = posting_stub(job)
            review = load_role_review(self.session, user_id=user_id, job=stub, query=query)
            from src.services.body_quality import readable_body
            unreadable = not readable_body(job.raw_content, title=job.title)
            uncertain = uncertain or unreadable
            match = classify_discovery_job(
                stub, query=query, conditions=conditions, role_review=review
            )
            needs_review = pending_review_fields(stub, query=query, conditions=conditions, role_review=review, primary=primary)
            if not include_body_reviews:
                needs_review = []
            if match.filter_status == "excluded" and not (unreadable or (primary and needs_review)):
                continue
            if not (stale or uncertain or needs_review):
                continue
            attempt = review_attempt(stub, conditions)
            reusable = not stale and not uncertain and verified <= now
            # Resume interrupted/budget-limited interpretation before old pages
            # consume the bounded batch. Missing facts/completed ambiguity are
            # removed by pending_review_fields, not repeatedly sent to a model.
            deferred = attempt.get("error_code") in {"semantic_budget", "semantic_pending", "semantic_cancelled"}
            rank = (0 if deferred else 1) if reusable and needs_review else 2
            queued_at = utc_time(attempt.get("queued_at") or attempt.get("attempted_at")) or verified or datetime.min.replace(tzinfo=UTC)
            # Scheduling hints use the saved body as well as the title. They
            # never replace the current model's eligibility decision.
            relevance = listing_priority(
                f"{job.title}\n{job.raw_content or ''}", query,
                conditions.get("job_types", []),
            ) if primary else (0, 0)
            last_attempt = utc_time(attempt.get("attempted_at")) or queued_at
            queued.append((relevance, rank, queued_at, job.id, group, job, last_attempt))

        selected = []
        while queued and len(selected) < limit:
            eligible = [item for item in queued if company_counts.get(item[4], 0) < 3]
            if not eligible:
                break
            # Reserve one slot in a normal batch for long-waiting unfamiliar
            # jobs. This prevents permanent keyword-based starvation.
            aged = [item for item in eligible if now - item[6] >= timedelta(days=1)]
            if primary and limit >= 4 and len(selected) == limit - 1 and aged:
                item = min(aged, key=lambda item: (item[6], item[2], item[3]))
            else:
                item = min(eligible, key=lambda item: (
                    item[0], company_counts.get(item[4], 0), *item[1:4],
                ))
            queued.remove(item)
            selected.append(item)
            company_counts[item[4]] = company_counts.get(item[4], 0) + 1

        for _, _, _, _, group, job, _ in selected:
            result.append(
                LeadCandidate(
                    provider=LeadProviderKind.EXTERNAL_AGENT,
                    source_url=job.source_url,
                    discovered_at=now,
                    title_hint=job.title,
                    company_hint=job.company,
                    source_id=job.source_id,
                )
            )
        return result

    def resume_candidates(self, user_id, *, goal_id, version, current_run_id, limit=16,
                          company_id=None, source_group=None, now=None, company_sources=None):
        """Resume latest unresolved observations, fairly across update attempts.

        Old failed observations cannot resurrect a subsequently verified, closed
        or ignored URL. A changed goal has its own verification scope.
        """
        from src.services.company_search_progress import CompanyProgressStore
        from src.services.lead_presentation import lead_discovery_kind
        from src.services.lead_retry import can_retry, lead_state, parser_retry_state

        entry_states = CompanyProgressStore(self.session, user_id=user_id,
            goal_id=goal_id, version=version).load_entries()

        now = now or datetime.now(UTC)

        rows = self.session.scalars(
            select(JobLead).join(DiscoveryRun, DiscoveryRun.id == JobLead.discovery_run_id)
            .where(JobLead.user_id == user_id, DiscoveryRun.user_id == user_id,
                   DiscoveryRun.search_goal_id == goal_id,
                   DiscoveryRun.search_goal_version == version,
                   DiscoveryRun.id != current_run_id)
            .order_by(DiscoveryRun.started_at.desc(), JobLead.created_at.desc(), JobLead.id.desc())
        )
        latest = {}
        for lead in rows:
            latest.setdefault(lead.normalized_url, lead)
        result = []
        def queue_order(lead):
            state = lead_state(lead)
            return (utc_time(state.get("queued_at")) or utc_time(lead.discovered_at),
                    utc_time(lead.updated_at), lead.id)

        if limit <= 0:
            return result
        for lead in sorted(latest.values(), key=queue_order):
            from src.services.company_scope import in_company_scope

            if not in_company_scope(lead, company_sources):
                continue
            if company_id and (
                source_group(lead.source_url, lead.company_hint) if source_group else lead.source_id
            ) != company_id:
                continue
            is_entry = lead_discovery_kind(lead) == "entry"
            if is_entry:
                if lead.failure_code not in {"entry_budget", "entry_no_progress", "entry_cooldown", "recruitment_entry_page"}:
                    continue
                due = utc_time(entry_states.get(lead.normalized_url, {}).get("next_retry_at"))
                if due and due > now:
                    continue
            if (lead.job_posting_id or lead.selection_status == "IGNORED"
                    or lead.status not in {"NEW", "DEFERRED", "FAILED", "NEEDS_BROWSER", "NEEDS_USER"}
                    or (not is_entry and not can_retry(parser_retry_state(self.session, lead), now=now))):
                continue
            result.append(LeadCandidate(
                provider=LeadProviderKind.EXTERNAL_AGENT, source_url=lead.source_url,
                discovered_at=datetime.now(UTC), title_hint=lead.title_hint,
                company_hint=lead.company_hint, search_snippet=lead.search_snippet,
                source_id=lead.source_id, source_job_id=lead.source_job_id,
                observed_title=(lead.extracted_fields or {}).get("page_type_basis") == "observed_listing",
                search_context={**(lead.extracted_fields or {}).get("search_context", {}), "resumed": True},
            ))
            if len(result) >= limit:
                break
        return result

    def cached_posting(self, user_id, url):
        """Reuse official body evidence without claiming that availability is known."""
        from sqlalchemy import and_, or_

        from src.services.job_url import canonical_job_url

        now = datetime.now(UTC)
        normalized = canonical_job_url(url)
        identity_ids = [job.id for job in self.postings(user_id)
                        if job.source_url and canonical_job_url(job.source_url) == normalized]
        linked_ids = set(self.session.scalars(select(JobLead.job_posting_id).where(
            JobLead.user_id == user_id, JobLead.normalized_url == normalized,
            JobLead.status.in_(["VERIFIED", "DUPLICATE"]), JobLead.job_posting_id.is_not(None),
        )))
        # Only observed verification links establish aliases. Never discard job
        # selectors or guess identity from equal titles on the same company.
        alias_id = next(iter(linked_ids)) if len(linked_ids) == 1 else None
        posting = self.session.scalar(
            select(JobPosting).join(CandidateJob, CandidateJob.job_posting_id == JobPosting.id)
            .where(CandidateJob.user_id == user_id, CandidateJob.status != "IGNORED",
                   or_(JobPosting.source_url == normalized, JobPosting.id == alias_id, JobPosting.id.in_(identity_ids)),
                   JobPosting.verification_status == "VERIFIED_OFFICIAL",
                   JobPosting.last_verified_at <= now,
                   or_(and_(JobPosting.availability_status == "ACTIVE",
                            JobPosting.last_verified_at >= now - timedelta(days=7)),
                       and_(JobPosting.availability_status == "UNKNOWN",
                            JobPosting.last_verified_at >= now - timedelta(days=1))))
            .order_by(JobPosting.last_verified_at.desc()).limit(1)
        )
        from src.services.body_quality import readable_body
        return posting if posting and readable_body(posting.raw_content, title=posting.title) else None

    def progress(self, user_id, goal_id):
        from src.services.body_review_queue import review_queue_summary
        from src.services.company_discovery_queue import discovery_queue_summary

        goal = self.get(user_id, goal_id)
        return {"goal_id": goal.id, "goal_version": goal.version,
                "review_queue": review_queue_summary(self.session, goal),
                "company_discovery_queue": discovery_queue_summary(self.session, goal)}

    def library(self, user_id, goal_id, *, include_progress=True, summary_only=False, compact=False, job_id=None):
        from src.domain.models import UserProfile
        from src.services.company_scope import goal_company_sources, in_company_scope
        from src.services.source_understanding import ai_policy_enabled

        primary = ai_policy_enabled()
        profile = self.session.get(UserProfile, user_id)
        from src.services.company_discovery import company_discovery_summary
        from src.services.company_discovery_queue import discovery_queue_summary
        from src.services.company_search_progress import progress_summaries
        goal = self.get(user_id, goal_id)
        company_sources = goal_company_sources(self.session, goal)
        runs = list(
            self.session.scalars(
                select(DiscoveryRun)
                .where(
                    DiscoveryRun.user_id == user_id,
                    DiscoveryRun.search_goal_id == goal.id,
                    DiscoveryRun.search_goal_version == goal.version,
                )
                .order_by(DiscoveryRun.started_at.desc(), DiscoveryRun.id.desc())
            )
        )
        latest = runs[0] if runs else None
        baseline = latest.library_baseline or {} if latest else {}
        matches, updates = [], []
        current_matches = {}
        now = datetime.now(UTC)
        for job in self.postings(user_id):
            if job_id and job.id != job_id:
                continue
            if not in_company_scope(job, company_sources):
                continue
            stub = posting_stub(job)
            match = classify_discovery_job(
                stub,
                query=goal.query,
                conditions=goal.conditions,
                role_review=None if primary else load_role_review(
                    self.session, user_id=user_id, job=stub, query=goal.query
                ),
            )
            match = apply_posting_availability(match, job, now=now).as_dict(job_posting_id=job.id)
            closed = job.availability_status == "CLOSED"
            match["goal_version"] = goal.version
            match["content_hash"] = job.content_hash
            from src.services.result_status import enrich_result

            match = enrich_result(match, job, profile, conditions=goal.conditions)
            from src.services.job_url import canonical_job_url

            current_matches[canonical_job_url(job.source_url or "")] = match["filter_status"]
            matches.append(match)
            previous = baseline.get(job.id)
            kind = (
                "new"
                if previous is None
                else "closed"
                if closed and previous["availability_status"] != "CLOSED"
                else "changed"
                if previous["content_hash"] != job.content_hash
                else None
            )
            # Unrelated saved jobs remain inspectable but do not inflate updates.
            if latest and latest.library_baseline is not None and kind and (
                match["filter_status"] != "excluded"
                or (kind == "closed" and previous.get("filter_status") != "excluded")
            ):
                updates.append(
                    {
                        "kind": kind,
                        "job_posting_id": job.id,
                        "title": job.title,
                        "company": job.company,
                        "filter_status": match["filter_status"],
                    }
                )
        if job_id:
            if not matches:
                raise LookupError("当前目标下未找到该岗位")
            return matches[0]
        counts = {
            **{s: sum(m["filter_status"] == s for m in matches) for s in ("matched", "pending", "excluded")},
            "closed": sum("closed" in m["mismatch_reasons"] for m in matches),
            "recommended": sum(m["review_status"] == "recommended" for m in matches),
            "needs_review": sum(m["review_status"] == "pending" for m in matches),
        }
        if summary_only:
            from src.domain.search_goal import BodyReviewTask
            task = self.session.get(BodyReviewTask, goal.id)
            return {"goal_id": goal.id, "goal_version": goal.version, "counts": counts,
                    "review_status": task.status if task and task.goal_version == goal.version else "idle",
                    "search_status": latest.status if latest else None,
                    "checked_at": now.isoformat()}
        matches.sort(
            key=lambda m: (
                {"recommended": 0, "pending": 1, "excluded": 2}[m["review_status"]],
                m["filter_status"] != "matched",
                -m["preference_score"],
            )
        )
        lead_ids = (
            list(
                self.session.scalars(
                    select(JobLead).where(
                        JobLead.user_id == user_id,
                        JobLead.discovery_run_id.in_([r.id for r in runs]),
                    )
                )
            )
            if runs
            else []
        )
        scoped_job_ids = {m["job_posting_id"] for m in matches}
        lead_ids = [lead.id for lead in lead_ids if lead.job_posting_id in scoped_job_ids
                    or in_company_scope(lead, company_sources)]
        from src.services.body_review_queue import review_queue_summary

        return {
            "goal_id": goal.id,
            "goal_version": goal.version,
            "query": goal.query,
            **({"review_queue": review_queue_summary(self.session, goal),
                "company_discovery_queue": discovery_queue_summary(self.session, goal)} if include_progress else {}),
            "result_matches": [compact_match(m) for m in matches] if compact else matches,
            "lead_ids": lead_ids,
            "latest_run_id": latest.id if latest else None,
            "company_progress": progress_summaries(goal, self.session,
                current_matches=current_matches if primary else None),
            "company_discovery": company_discovery_summary(self.session, user_id),
            "updates": updates,
            "counts": counts,
        }


def compact_match(match):
    """Keep list decisions; load full quotations only when a job is opened."""
    check_keys = {"field", "status", "reason", "diagnosis", "role_relation", "review_required", "required"}
    return {**{k: match[k] for k in ("job_posting_id", "goal_version", "filter_status", "review_status",
            "match_tier", "mismatch_reasons", "mismatch_labels", "preference_score", "personal_gate_conflict",
            "review_caveats", "result_status") if k in match},
        "details_compact": True,
        "checks": [{**{k: v for k, v in c.items() if k in check_keys}, "evidence": []} for c in match.get("checks", [])],
        "personal_requirements": [{k: v for k, v in h.items() if k in {"category", "status", "label", "reason"}}
                                  for h in match.get("personal_requirements", []) if h["status"] in {"attention", "source_conflict"}]}
