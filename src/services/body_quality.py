"""Detect transport defects without treating omitted job facts as read failures."""

import re

VERSION = "body-quality-v1"
TEMPLATE = re.compile(r"\{\{\s*(?:[$\w]+(?:\.[\w]+)*|\$t\([^}]*\)|[\w]+\s*\|[^}]+)\s*\}\}|<%[=-].*?%>")
FIELD = r"(?:岗位职责|工作职责|任职要求|职位要求|岗位要求|职位描述|工作地点|main responsibilities|responsibilities|requirements|qualifications|job location)"
HEADING = re.compile(r"^" + FIELD + r"\s*[:：]?\s*$", re.IGNORECASE)
FIELD_BINDING = re.compile(FIELD + r"\s*[:：]?\s*(?:" + TEMPLATE.pattern + r")", re.IGNORECASE)
LOADING = re.compile(r"^(?:正在加载|加载中|请稍候|loading|please wait)[.。…\s]*$", re.IGNORECASE)
REFERENCE = re.compile(r"(?:请(?:您)?\s*)?(?:详见|参见|请见)[^。；;\n]{0,70}(?:岗位职责|岗位要求|岗位说明|职位说明|详情|附件|公告|链接|页面)[。.]?"
                       r"|(?:please\s+)?(?:see|refer to)\s+(?:the\s+)?(?:attached\s+)?(?:job description|position description|attachment|link|details)[.。]?", re.IGNORECASE)


def referenced_duties(text):
    section = re.search(r"(?:岗位职责|工作职责|职责描述|Main Responsibilities|Responsibilities)\s*[:：]?\s*"
                        r"(.+?)(?=\n\s*(?:任职要求|职位要求|岗位要求|Requirements|Qualifications)\s*[:：]?|$)",
                        text, re.IGNORECASE | re.DOTALL)
    if not section:
        return False
    lines = [line.strip() for line in section[1].splitlines() if line.strip()]
    return bool(lines) and all(REFERENCE.fullmatch(line) for line in lines)


def assess_body(text, *, title=None):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    substantive = [line for line in lines if not HEADING.fullmatch(line)
                   and not LOADING.fullmatch(line) and line != title]
    state, reason = "readable", None
    if not substantive:
        state, reason = "empty", "页面只有标题或加载提示，尚未读到岗位正文"
    elif any(TEMPLATE.search(line) for line in substantive):
        # A literal template in an explanatory sentence is valid content. A
        # field whose entire value is a binding is an unfinished page instead.
        broken = [line for line in substantive if TEMPLATE.search(line)
                  and not TEMPLATE.sub("", line).strip(" :：|/、，。-;")]
        # HTML text extraction can collapse several sections into one line.
        # A field immediately followed by its binding is still unfinished.
        if (broken and len(broken) == len(substantive)) or FIELD_BINDING.search(text):
            state, reason = "incomplete", "岗位字段仍是未渲染的模板占位符，需要重新读取页面"
    if state == "readable" and referenced_duties(text):
        state, reason = "reference_only", "当前页只指向另一份岗位说明，尚未读到具体职责"
    return {"version": VERSION, "status": state, "reason": reason}


def readable_body(text, *, title=None):
    return assess_body(text, title=title)["status"] == "readable"
