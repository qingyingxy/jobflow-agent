"""Exact job-bound facts from observed public recruitment templates.

No page-wide keywords, undocumented numeric status mappings or JS evaluation.
"""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit


def alibaba_job_id(url):
    parsed = urlsplit(url)
    match = re.fullmatch(r"/campus/position/(\d+)/?", parsed.path)
    return match[1] if parsed.scheme == "https" and parsed.netloc == "campus-talent.alibaba.com" and match else None


def alibaba_detail_api(response_url, page_url):
    parsed = urlsplit(response_url)
    return bool(alibaba_job_id(page_url) and parsed.scheme == "https"
                and parsed.netloc == "campus-talent.alibaba.com" and parsed.path == "/position/detail")


def template_context(*, url, raw_html, document, api_records, base, save_snapshot):
    job_id = alibaba_job_id(url)
    if job_id:
        records = [r for r in api_records if alibaba_detail_api(r.get("url", ""), url)
                   and str((r.get("request") or {}).get("id")) == job_id]
        if not records:
            return None
        # Repeated responses must agree on the exact job, not a recommendation.
        payloads = [r.get("payload") for r in records]
        if any(p != payloads[0] for p in payloads):
            raise ValueError("detail_payload_conflict")
        payload = payloads[0]
        item = payload.get("content") if isinstance(payload, dict) and payload.get("success") is True else None
        if not isinstance(item, dict) or str(item.get("id")) != job_id or item.get("name") != document.title:
            raise ValueError("detail_identity_conflict")
        endpoint = "https://campus-talent.alibaba.com/position/detail"
        # Strip ephemeral request tokens; retain only public job facts and ID.
        snapshot_id = save_snapshot(endpoint, json.dumps({"request": {"id": job_id}, "payload": payload}, ensure_ascii=False))
        eligibility = "招聘项目：" + (item.get("batchName") or "")
        window = item.get("graduationTime")
        window = {} if window is None else window
        if not isinstance(window, dict):
            raise ValueError("graduation_window_invalid")
        if window:
            dates = []
            for key in ("from", "to"):
                if type(window.get(key)) not in {int, float} or not 946684800000 <= window[key] <= 4102444800000:
                    raise ValueError("graduation_window_invalid")
                dates.append(datetime.fromtimestamp(window[key] / 1000, timezone(timedelta(hours=8))).strftime("%Y年%m月%d日"))
            if window["from"] > window["to"]:
                raise ValueError("graduation_window_invalid")
            eligibility += "\n毕业时间要求：" + "至".join(dates)
        # 'recruit' is an explicit textual status in this job's detail response.
        # Corroborate it with the same detail page's current recruiting business region.
        business = re.search(r"(?:^|\n)在招业务\s*\n(.+)", document.text)
        opened = item.get("status") == "recruit" and isinstance(item.get("circleNames"), list) and bool(business) and any(
            isinstance(name, str) and name and name in business[1] for name in item["circleNames"])
        return {
            **base, "version": 2, "status": "verified", "association": "official_job_payload",
            "template": "alibaba_campus_v1", "job_id": job_id,
            "batch_id": str(item.get("batchId") or ""), "batch_name": item.get("batchName"),
            "source_url": endpoint, "snapshot_id": snapshot_id, "eligibility_text": eligibility,
            "availability": {"value": "ACTIVE" if opened else "UNKNOWN", "source_url": endpoint,
                             "source_text": "status=recruit；在招业务" if opened else None,
                             "reason": None if opened else "未确认该岗位当前在招业务"},
        }
    parsed = urlsplit(url)
    match = re.fullmatch(r"/jobs/detail/(GRADUATE|INTERN|SOCIAL)/([a-zA-Z0-9-]+)/?", parsed.path)
    if parsed.scheme != "https" or parsed.netloc != "talent.baidu.com" or not match:
        return None
    # Decode JSON data only, never execute the script surrounding it.
    scripts = re.findall(r"<script\b[^>]*>(.*?)</script\s*>", raw_html, re.DOTALL | re.IGNORECASE)
    data = []
    for script in scripts:
        marker = re.search(r"window\.__INITIAL_DATA__\s*=\s*", script)
        if marker:
            data.append(json.JSONDecoder().raw_decode(script[marker.end():])[0])
    if len(data) != 1:
        return None
    if not isinstance(data[0], dict):
        raise TypeError("detail_payload_invalid")
    detail = data[0].get("detailData") or {}
    if not isinstance(detail, dict):
        raise TypeError("detail_payload_invalid")
    item = detail.get("postInfo") or {}
    if not isinstance(item, dict):
        raise TypeError("detail_payload_invalid")
    if item.get("postId") != match[2] or item.get("name") != document.title or detail.get("recruitType") != match[1]:
        raise ValueError("detail_identity_conflict")
    # Only the matching recruitment type's project description, not unrelated
    # list cards or the internship announcement in the same SSR payload.
    index = data[0].get("indexData") or {}
    if not isinstance(index, dict) or not isinstance(index.get("schoolProjectConfig", []), list):
        raise TypeError("batch_payload_invalid")
    projects = []
    for group in index.get("schoolProjectConfig", []):
        if not isinstance(group, dict) or not isinstance(group.get("childList", []), list):
            raise TypeError("batch_payload_invalid")
        projects.extend(p for p in group.get("childList", [])
                        if isinstance(p, dict) and p.get("recruitType") == match[1])
    if len(projects) != 1 or item.get("projectTypeCode") != "1" or detail.get("projectType") != "1":
        return None  # Special talent projects require their own eligibility proof.
    endpoint = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    snapshot_id = save_snapshot(endpoint, json.dumps({"detailData": detail, "project": projects[0]}, ensure_ascii=False))
    return {**base, "version": 2, "status": "verified", "association": "official_job_project_id",
            "template": "baidu_campus_v1", "job_id": match[2], "batch_id": "1",
            "batch_name": projects[0].get("title"), "source_url": endpoint,
            "snapshot_id": snapshot_id, "eligibility_text": projects[0].get("content") or "",
            "availability": {"value": "UNKNOWN", "source_url": endpoint,
                             "reason": "页面有效标记不等于岗位开放，仍需明确在招证据"}}
