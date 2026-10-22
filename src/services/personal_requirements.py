"""Fast, conservative source notices, not a replacement for personal JD analysis."""

import re

from src.domain.education import DEGREE_LABELS, DEGREE_RANK, degree_levels
from src.services.qualification_understanding import cached_qualifications

LABELS = {"degree": "学历要求", "major": "专业要求", "experience": "经验要求",
          "institution": "院校要求", "publication": "论文与研究成果要求", "other": "其他任职要求"}


def qualification_hints(job, clauses, highest):
    hints = []
    for clause in clauses:
        preferred = clause["strength"] == "preferred"
        status = "preferred" if preferred else "review"
        note = "加分项，不作为硬性淘汰条件" if preferred else "原文有此要求，个人资料尚未核对"
        if clause["strength"] in {"conditional", "uncertain"} or clause["scope"]:
            note = ("加分项，不作为硬性淘汰条件；" if preferred else "") + "此条件包含适用范围或例外，请核对完整原文" + (f"：{clause['scope']}" if clause["scope"] else "")
        elif clause["category"] == "degree" and clause["strength"] == "required" and highest and clause["accepted_degrees"]:
            floor = min(DEGREE_RANK[level] for level in clause["accepted_degrees"])
            if DEGREE_RANK[highest] < floor:
                status = "attention"
                required = "、".join(DEGREE_LABELS[level] for level in clause["accepted_degrees"])
                note = f"原文必备学历为{required}，当前资料最高学历为{DEGREE_LABELS[highest]}，存在明确门槛冲突"
            elif highest in clause["accepted_degrees"]:
                status, note = "satisfied", "当前学历达到本条要求；其他任职条件仍需分别核对"
            else:
                note = "当前学历不在原文明列的选项中，需核对是否接受其他学历；暂不判定符合或排除"
        hints.append({"category": clause["category"], "status": status, "label": LABELS[clause["category"]],
                      "reason": note, "evidence": clause["evidence"], "source_url": job.source_url, "source": "ai"})
    return hints


def scoped_requirement_lines(job, scopes):
    """Fallback only: separate numbered clauses and inline bonus headings.

    Keep the original line as evidence, including alternative paths. Semantic
    cached clauses, when available, take precedence over this conservative aid.
    """
    for original in requirement_lines(job):
        bonus, branch = scopes.get(original, (False, None))
        pieces = re.split(r"(?=优先条件|加分项|Nice to have|Bonus)|(?<=[；;。])\s*|\s+(?=\d+[.、])", original, flags=re.IGNORECASE)
        for piece in pieces:
            if not piece.strip():
                continue
            if re.match(r"(?:优先条件|加分项|Nice to have|Bonus)", piece, re.IGNORECASE):
                bonus = True
            yield piece, original, bonus, branch


def requirement_lines(job):
    from src.services.source_understanding import semantic_sections

    sections = semantic_sections(job)
    if sections:
        return sections["requirements"]
    text = job.raw_content or ""
    heading = re.search(r"任职(?:要求|资格)|岗位要求|职位要求|申请要求|Qualifications|Requirements", text, re.IGNORECASE)
    if not heading:
        return []
    text = text[heading.end():]
    # Stop at employer/team sections as well as responsibilities. A team's
    # existing degrees or institutions are not requirements for the candidate.
    text = re.split(r"岗位职责|工作职责|公司介绍|福利待遇|Responsibilities|About us|"
                    r"(?:^|\n)\s*[【\[#]*\s*(?:团队介绍|关于我们|为什么(?:是|选择|加入)我们|"
                    r"我们提供|你将获得|薪酬福利|About the team|Why (?:us|join us)|What we offer)"
                    r"\s*(?:[】\]:：]|$)", text, flags=re.IGNORECASE | re.MULTILINE)[0]
    return [line.strip() for line in text.splitlines() if line.strip()]


def personal_requirement_hints(job, profile):
    levels = set(degree_levels(profile.degree or "")) if profile else set()
    for education in (profile.educations or []) if profile else []:
        if education.get("level") in DEGREE_RANK:
            levels.add(education["level"])
    highest = max(levels, key=lambda value: DEGREE_RANK.get(value, -1)) if levels else None
    clauses = cached_qualifications(job)
    if clauses is not None:
        return qualification_hints(job, clauses, highest)
    hints = []
    # Semantic extraction may omit section headings from requirement_ids. Read
    # their scope in the original body so a bonus section stays optional.
    scopes = {}
    bonus, branch = False, None
    in_duties = False
    for raw_line in (job.raw_content or "").splitlines():
        raw_line = raw_line.strip()
        heading = raw_line.strip("【】[]（）() :：")
        if re.fullmatch(r"(?:\d+[.、\s]*)?(?:加分项|优先条件|优先项|Bonus|Nice to have)", heading, re.IGNORECASE):
            bonus = True
        elif re.fullmatch(r"(?:任职要求|任职资格|岗位要求|职位要求|申请要求|Qualifications|Requirements)", heading, re.IGNORECASE):
            bonus = False
            if in_duties:
                branch = None
            in_duties = False
        elif re.fullmatch(r"(?:主要职责|岗位职责|工作职责|Responsibilities)", heading, re.IGNORECASE):
            bonus, branch = False, None
            in_duties = True
        elif re.fullmatch(r"(?:基本要求|必备条件|必要条件)", heading):
            bonus = False
        elif re.fullmatch(r".{1,35}方向|方向[一二三四五\d：:\s].{0,35}", heading):
            branch, bonus = raw_line, False
        scopes[raw_line] = (bonus, branch)
    for line, original, bonus, branch in scoped_requirement_lines(job, scopes):
        preferred = bonus or bool(re.search(r"优先|加分|更佳|preferred|plus\b", line, re.IGNORECASE))
        categories = []
        if re.search(r"博士|硕士|本科|学历|学位|Ph\.?D|master|bachelor", line, re.IGNORECASE):
            categories.append(("degree", "学历要求"))
        if re.search(r"985|211|双一流|QS\s*(?:前|top)?\s*\d+|院校|名校", line, re.IGNORECASE):
            categories.append(("institution", "院校要求"))
        if re.search(r"一作|第一作者|顶会|论文|first.author|publication", line, re.IGNORECASE):
            # Reading papers is also a skill requirement; this fallback cannot
            # assume every mention of a paper requires publication experience.
            categories.append(("publication", "论文相关要求"))
        if re.search(r"\d+\s*年.{0,18}(?:经验|经历)|工作经验|工作经历|\d+\+?\s*years?", line, re.IGNORECASE):
            categories.append(("experience", "经验要求"))
        for category, label in categories:
            status = "preferred" if preferred else "review"
            note = "加分项，不作为硬性淘汰条件" if preferred else "请结合个人资料核对，尚未完成完整任职资格分析"
            if not preferred and category == "experience":
                note = "原文有经验要求；当前未核对你的相关经历，不据此推断社招或自动排除"
            if branch:
                note = f"适用于「{branch}」，请确认所选方向；" + note
            degree_only_phd = (category == "degree" and bool(re.search(
                r"博士(?:研究生)?(?:学历|学位|毕业|及以上|应届生)|(?:学历|学位)(?:要求)?[：:\s]*博士|Ph\.?D\.?\s+(?:degree|in\b)", line, re.IGNORECASE))
                and not re.search(r"硕士|本科|专科|博士后|放宽|优先|加分|如果|若|不限|不要求|无需|不需要|不必|非必须|不强制|master|bachelor", line, re.IGNORECASE)
                and not re.search(r"放宽|如果|若|无需|不要求", original))
            if degree_only_phd and not preferred and not branch and highest and DEGREE_RANK[highest] < DEGREE_RANK["doctor"]:
                status = "attention"
                note = f"原文要求博士，当前资料最高学历为{DEGREE_LABELS[highest]}；投递前需核对"
            floor = re.search(r"(本科|硕士)(?:研究生)?(?:及以上|以上)?(?:学历|学位)", line)
            if (category == "degree" and floor and not preferred and not branch and highest
                    and not re.search(r"或|放宽|如果|若|不限|不要求|无需|非必须|不强制", line)):
                required = {"本科": "bachelor", "硕士": "master"}[floor[1]]
                if DEGREE_RANK[highest] < DEGREE_RANK[required]:
                    status = "attention"
                    note = f"原文要求{floor[1]}，当前资料最高学历为{DEGREE_LABELS[highest]}；投递前需核对"
            hints.append({"category": category, "status": status, "label": label,
                          "reason": note, "evidence": original, "source_url": job.source_url, "source": "local"})
    # Preserve entire clauses, including alternatives; never claim that an empty
    # list means all requirements passed or infer failure from a missing resume fact.
    return list({(h["category"], h["evidence"], h["status"]): h for h in hints}.values())[:12]
