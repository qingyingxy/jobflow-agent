from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from src.domain.ats_assistance import (
    AtsFieldAction,
    AtsFieldRisk,
    AtsProvider,
)


class AtsAdapterError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AtsFieldDescriptor:
    key: str
    label: str
    name: str
    input_type: str
    required: bool
    selector: str
    options: tuple[str, ...] = ()
    autocomplete: str | None = None


@dataclass(frozen=True)
class AtsPageSnapshot:
    requested_url: str
    final_url: str
    title: str
    visible_text: str
    fields: tuple[AtsFieldDescriptor, ...]
    form_action: str | None = None
    provider_hint: AtsProvider | None = None
    gates: tuple[str, ...] = ()

    @property
    def fingerprint(self) -> str:
        return _hash_json(
            {
                "final_url": self.final_url,
                "form_action": self.form_action,
                "fields": [
                    {
                        "key": field.key,
                        "label": field.label,
                        "name": field.name,
                        "input_type": field.input_type,
                        "required": field.required,
                        "options": list(field.options),
                    }
                    for field in self.fields
                ],
            }
        )


@dataclass(frozen=True)
class AtsFillOperation:
    field_key: str
    selector: str
    input_type: str
    value: str


@dataclass(frozen=True)
class AtsPreparationResult:
    page_fingerprint: str
    filled_field_keys: tuple[str, ...]
    verification_issues: tuple[str, ...] = ()


@dataclass(frozen=True)
class AtsSubmissionEvidence:
    success: bool
    confirmation_text: str | None
    confirmation_url: str | None
    application_number: str | None
    captured_at: datetime
    failure_code: str | None = None


class AtsBrowserExecutor(Protocol):
    async def inspect(self, url: str) -> AtsPageSnapshot:
        ...

    async def prepare(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsPreparationResult:
        ...

    async def submit(
        self,
        *,
        url: str,
        provider: AtsProvider,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        ...


class AtsAdapter(Protocol):
    provider: AtsProvider

    def detect(self, snapshot: AtsPageSnapshot) -> bool:
        ...

    def inspect(self, snapshot: AtsPageSnapshot) -> list[AtsFieldDescriptor]:
        ...

    def map_fields(
        self,
        snapshot: AtsPageSnapshot,
        packet: dict[str, Any],
        confirmations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        ...

    def fill(self, field_plan: list[dict[str, Any]]) -> list[AtsFillOperation]:
        ...

    def verify(
        self,
        prepared: AtsPreparationResult,
        field_plan: list[dict[str, Any]],
        expected_fingerprint: str,
    ) -> list[str]:
        ...

    def request_approval(
        self,
        *,
        snapshot: AtsPageSnapshot,
        field_plan: list[dict[str, Any]],
        packet: dict[str, Any],
    ) -> dict[str, Any]:
        ...

    async def submit(
        self,
        executor: AtsBrowserExecutor,
        *,
        url: str,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        ...

    def capture_receipt(self, evidence: AtsSubmissionEvidence) -> dict[str, Any]:
        ...


class StructuredAtsAdapter:
    provider: AtsProvider
    hosts: frozenset[str]

    def detect(self, snapshot: AtsPageSnapshot) -> bool:
        if snapshot.provider_hint is self.provider:
            return True
        hosts = {
            (urlsplit(snapshot.final_url).hostname or "").casefold(),
            (urlsplit(snapshot.form_action or "").hostname or "").casefold(),
        }
        return bool(hosts & self.hosts)

    def inspect(self, snapshot: AtsPageSnapshot) -> list[AtsFieldDescriptor]:
        return list(snapshot.fields)

    def map_fields(
        self,
        snapshot: AtsPageSnapshot,
        packet: dict[str, Any],
        confirmations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        confirmed = {
            (str(item.get("field_key")), str(item.get("value_hash")))
            for item in confirmations
        }
        plans: list[dict[str, Any]] = []
        for field in self.inspect(snapshot):
            canonical = _canonical_field(field)
            risk = _field_risk(field, canonical)
            value, source = _resolve_value(field, canonical, packet)
            value_hash = _hash_text(value) if value is not None else None
            if field.input_type == "custom_select":
                action = AtsFieldAction.NEEDS_USER
                reason = "自定义下拉框不在当前自动操作范围内，必须由用户处理"
            elif field.input_type == "file" and canonical != "resume":
                action = AtsFieldAction.NEEDS_USER
                reason = "非简历文件上传不在当前自动操作范围内，必须由用户处理"
            elif value is None:
                action = (
                    AtsFieldAction.NEEDS_VALUE
                    if field.required
                    else AtsFieldAction.SKIP
                )
                reason = (
                    "已批准投递包中没有这个必填字段的来源"
                    if field.required
                    else "可选字段没有已批准来源，保持为空"
                )
            elif risk in {
                AtsFieldRisk.PERSONAL,
                AtsFieldRisk.HIGH_IMPACT,
                AtsFieldRisk.LEGAL,
            } and (field.key, value_hash or "") not in confirmed:
                action = AtsFieldAction.NEEDS_CONFIRMATION
                reason = "该字段影响较高，必须由用户针对本次表单再次确认"
            else:
                action = AtsFieldAction.FILL
                reason = "值来自当前已批准的投递包"
            plans.append(
                {
                    "field_key": field.key,
                    "label": field.label,
                    "name": field.name,
                    "input_type": field.input_type,
                    "required": field.required,
                    "selector": field.selector,
                    "canonical_name": canonical,
                    "risk": risk.value,
                    "action": action.value,
                    "source": source,
                    "value": value,
                    "value_hash": value_hash,
                    "reason": reason,
                    "options": list(field.options),
                }
            )
        return plans

    def fill(self, field_plan: list[dict[str, Any]]) -> list[AtsFillOperation]:
        return [
            AtsFillOperation(
                field_key=str(item["field_key"]),
                selector=str(item["selector"]),
                input_type=str(item["input_type"]),
                value=str(item["value"]),
            )
            for item in field_plan
            if item.get("action") == AtsFieldAction.FILL.value
            and item.get("value") is not None
        ]

    def verify(
        self,
        prepared: AtsPreparationResult,
        field_plan: list[dict[str, Any]],
        expected_fingerprint: str,
    ) -> list[str]:
        issues = list(prepared.verification_issues)
        if prepared.page_fingerprint != expected_fingerprint:
            issues.append("ats_page_changed")
        filled = set(prepared.filled_field_keys)
        for item in field_plan:
            if item.get("action") == AtsFieldAction.FILL.value and str(
                item.get("field_key")
            ) not in filled:
                issues.append(f"field_not_filled:{item.get('field_key')}")
        return list(dict.fromkeys(issues))

    def request_approval(
        self,
        *,
        snapshot: AtsPageSnapshot,
        field_plan: list[dict[str, Any]],
        packet: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": self.provider.value,
            "company": packet.get("job_snapshot", {}).get("company"),
            "job_title": packet.get("job_snapshot", {}).get("title"),
            "application_url": snapshot.final_url,
            "packet_revision_id": packet.get("id"),
            "resume": packet.get("resume_snapshot", {}).get("label"),
            "field_count": len(field_plan),
            "fill_count": sum(
                item.get("action") == AtsFieldAction.FILL.value
                for item in field_plan
            ),
            "key_answers": [
                {
                    "field_key": item.get("field_key"),
                    "label": item.get("label"),
                    "value": item.get("value"),
                    "risk": item.get("risk"),
                    "source": item.get("source"),
                }
                for item in field_plan
                if item.get("action") == AtsFieldAction.FILL.value
            ],
        }

    async def submit(
        self,
        executor: AtsBrowserExecutor,
        *,
        url: str,
        operations: list[AtsFillOperation],
    ) -> AtsSubmissionEvidence:
        return await executor.submit(
            url=url,
            provider=self.provider,
            operations=operations,
        )

    def capture_receipt(self, evidence: AtsSubmissionEvidence) -> dict[str, Any]:
        text = " ".join((evidence.confirmation_text or "").split())
        if not evidence.success or not has_submission_success_marker(text):
            raise AtsAdapterError(
                "ATS 页面没有提供可验证的提交成功信息",
                code=evidence.failure_code or "ats_submission_unverified",
            )
        return {
            "confirmation_text": text,
            "confirmation_url": evidence.confirmation_url,
            "application_number": evidence.application_number,
            "captured_at": evidence.captured_at,
        }


class GreenhouseAdapter(StructuredAtsAdapter):
    provider = AtsProvider.GREENHOUSE
    hosts = frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"})


class LeverAdapter(StructuredAtsAdapter):
    provider = AtsProvider.LEVER
    hosts = frozenset({"jobs.lever.co"})


class AtsAdapterRegistry:
    def __init__(self, adapters: list[AtsAdapter] | None = None) -> None:
        self.adapters = adapters or [GreenhouseAdapter(), LeverAdapter()]

    def detect(self, snapshot: AtsPageSnapshot) -> AtsAdapter:
        matches = [adapter for adapter in self.adapters if adapter.detect(snapshot)]
        if len(matches) != 1:
            raise AtsAdapterError(
                "当前页面不是受支持的 Greenhouse 或 Lever 申请表",
                code="unsupported_ats",
            )
        return matches[0]

    def for_provider(self, provider: AtsProvider) -> AtsAdapter:
        for adapter in self.adapters:
            if adapter.provider is provider:
                return adapter
        raise AtsAdapterError("ATS Adapter 不存在", code="unsupported_ats")


def plan_hash(field_plan: list[dict[str, Any]]) -> str:
    return _hash_json(
        {
            "fields": [
                {
                    key: value
                    for key, value in item.items()
                    if key not in {"selector", "reason"}
                }
                for item in field_plan
            ]
        }
    )


def blocking_reasons(
    snapshot: AtsPageSnapshot, field_plan: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    reasons = [
        {
            "code": gate,
            "category": "human_gate",
            "message": "页面要求用户完成人工验证后才能继续",
        }
        for gate in snapshot.gates
    ]
    reasons.extend(
        {
            "code": (
                "sensitive_field_confirmation_required"
                if item.get("action") == AtsFieldAction.NEEDS_CONFIRMATION.value
                else (
                    "unsupported_field_control"
                    if item.get("action") == AtsFieldAction.NEEDS_USER.value
                    else "approved_value_missing"
                )
            ),
            "category": "field",
            "field_key": item.get("field_key"),
            "label": item.get("label"),
            "message": item.get("reason"),
        }
        for item in field_plan
        if item.get("action")
        in {
            AtsFieldAction.NEEDS_CONFIRMATION.value,
            AtsFieldAction.NEEDS_VALUE.value,
            AtsFieldAction.NEEDS_USER.value,
        }
    )
    return reasons


def has_submission_success_marker(text: str) -> bool:
    folded = " ".join(text.casefold().split())
    markers = (
        "application submitted",
        "application has been submitted",
        "application was submitted",
        "application received",
        "received your application",
        "thank you for applying",
        "thank you for your application",
        "application complete",
        "提交成功",
        "申请已提交",
        "申请提交成功",
        "已收到你的申请",
        "已收到您的申请",
        "感谢你的申请",
        "感谢您的申请",
    )
    return any(marker in folded for marker in markers)


def _canonical_field(field: AtsFieldDescriptor) -> str:
    text = _fold(f"{field.label} {field.name} {field.autocomplete or ''}")
    if field.input_type == "file":
        return (
            "resume"
            if _contains(text, "resume", "curriculum vitae", "cv", "简历")
            else "unsupported_file"
        )
    if field.input_type == "email" or _contains(text, "email", "邮箱", "电子邮件"):
        return "contact_email"
    if field.input_type == "tel" or _contains(text, "phone", "mobile", "电话", "手机"):
        return "contact_phone"
    if _contains(text, "sponsorship", "sponsor", "签证担保", "需要担保"):
        return "sponsorship_required"
    if _contains(text, "work authorization", "authorized to work", "工作资格", "工作许可"):
        return "work_authorization"
    if _contains(text, "salary", "compensation", "薪资", "期望薪酬"):
        return "salary_strategy"
    if _contains(text, "relocation", "搬迁", "异地"):
        return "relocation_willing"
    if _contains(
        text,
        "gender",
        "race",
        "ethnicity",
        "veteran",
        "disability",
        "性别",
        "种族",
        "残障",
        "退伍",
    ):
        return "voluntary_disclosure"
    if field.input_type == "checkbox" and _contains(
        text, "privacy", "consent", "terms", "隐私", "同意", "条款"
    ):
        return "legal_consent"
    return "custom_answer"


def _field_risk(field: AtsFieldDescriptor, canonical: str) -> AtsFieldRisk:
    if canonical == "legal_consent":
        return AtsFieldRisk.LEGAL
    if canonical in {
        "work_authorization",
        "sponsorship_required",
        "salary_strategy",
        "relocation_willing",
    }:
        return AtsFieldRisk.HIGH_IMPACT
    if canonical == "voluntary_disclosure":
        return AtsFieldRisk.PERSONAL
    return AtsFieldRisk.LOW


def _resolve_value(
    field: AtsFieldDescriptor,
    canonical: str,
    packet: dict[str, Any],
) -> tuple[str | None, str | None]:
    if canonical == "resume":
        asset = packet.get("resume_snapshot", {}).get("asset", {})
        asset_id = asset.get("id")
        return (str(asset_id), "resume_snapshot") if asset_id else (None, None)
    if canonical == "legal_consent":
        return "true", "user_confirmation"
    if canonical == "voluntary_disclosure":
        policy = packet.get("profile_snapshot", {}).get(
            "voluntary_disclosure_policy"
        )
        if policy == "prefer_not_to_answer":
            return "Prefer not to answer", "private_profile"
    if canonical != "custom_answer":
        entry = packet.get("profile_snapshot", {}).get(canonical, {})
        if entry.get("state") == "provided" and entry.get("value") is not None:
            value = entry["value"]
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            return str(value), "private_profile"
    question = _fold(f"{field.label} {field.name}")
    candidates = [
        *packet.get("form_answer_snapshots", []),
        *packet.get("open_questions", []),
    ]
    for item in candidates:
        pattern = _fold(
            str(item.get("question_pattern") or item.get("question") or "")
        )
        answer = item.get("answer")
        if answer is not None and pattern and (
            pattern in question or question in pattern
        ):
            return str(answer), f"approved_answer:{item.get('id')}"
    return None, None


def _fold(value: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value.casefold()).strip()


def _contains(text: str, *markers: str) -> bool:
    return any(_fold(marker) in text for marker in markers)


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hash_json(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def snapshot_to_dict(snapshot: AtsPageSnapshot) -> dict[str, Any]:
    return {
        **asdict(snapshot),
        "provider_hint": (
            snapshot.provider_hint.value if snapshot.provider_hint else None
        ),
    }
