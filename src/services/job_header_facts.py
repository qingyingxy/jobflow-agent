"""Literal location fields in the current job's header, never prose mentions."""

import re

_HEADER_END = re.compile(
    r"岗位描述|岗位职责|工作职责|职位描述|职位职责|任职要求|岗位要求|职位要求|职责描述|"
    r"responsibilities|qualifications|requirements|job description|相关职位|推荐职位",
    re.IGNORECASE,
)
_CITIES = [
    "北京",
    "上海",
    "深圳",
    "广州",
    "杭州",
    "成都",
    "南京",
    "武汉",
    "苏州",
    "西安",
    "天津",
    "重庆",
    "厦门",
    "合肥",
    "长沙",
    "郑州",
    "济南",
    "青岛",
    "宁波",
    "无锡",
    "福州",
    "大连",
    "沈阳",
    "长春",
    "哈尔滨",
    "石家庄",
    "太原",
    "南昌",
    "南宁",
    "昆明",
    "贵阳",
    "海口",
    "兰州",
    "西宁",
    "银川",
    "乌鲁木齐",
    "呼和浩特",
    "拉萨",
    "珠海",
    "东莞",
    "佛山",
    "惠州",
    "香港",
    "澳门",
    "台北",
    "新加坡",
    "圣何塞",
    "西雅图",
    "巴黎",
    "伦敦",
    "东京",
]
_CITY = r"(?:中国)?(?:" + "|".join(map(re.escape, _CITIES)) + r")(?:市)?"
_HEADER_FIELD = (
    r"(?:校招|校园招聘|社招|社会招聘|实习|实习生|全职|兼职|正式|"
    r"技术|研发|产品|设计|运营|市场|销售|职能|"
    r"[A-Za-z0-9\u4e00-\u9fff]{1,20}(?:项目|计划)|"
    r"\d+人|若干(?:人)?|20\d{2}[-/]\d{1,2}[-/]\d{1,2})"
)
_LOCATION_LINE = re.compile(
    rf"(?P<locations>{_CITY}(?:[ \t]*[/、,，|][ \t]*{_CITY})*)"
    rf"(?:[ \t]+{_HEADER_FIELD})*"
)
_LOCATION_NAVIGATION = re.compile(
    r"(?:(?:点击)?(?:查看|浏览|搜索|筛选|选择)(?:更多|全部|所有)?"
    r"(?:工作岗位|工作地点|办公地点|岗位|职位|城市)|"
    r"(?:view|browse|search|select|filter) (?:all |more )?(?:jobs|positions|locations))",
    re.IGNORECASE,
)


def location_field_values(values: list[str]) -> list[str]:
    """Remove UI action labels, retaining unknown but potentially real locations."""
    return [
        value for value in values if not _LOCATION_NAVIGATION.fullmatch(value.strip())
    ]


def header_location_evidence(text: str, title: str | None) -> list[dict]:
    """Require a literal title with optional inline cities and a bounded header.

    The whole line must be city fields plus recognized header metadata fields.
    Thus company introductions, references
    to other cities in duties, and partially understood lists cannot prove a
    work location. HTML navigation/related jobs must already be scoped out.
    """
    if not title:
        return []
    heading = re.search(
        rf"(?m)^[ \t]*{re.escape(title.strip())}(?:[ \t]+(?P<cities>[^\n]+?))?[ \t]*$",
        text,
    )
    end = _HEADER_END.search(text, heading.end()) if heading else None
    if not heading or not end or end.start() - heading.end() > 1200:
        return []
    result = []
    lines = [
        (line[0], heading.end() + line.start())
        for line in re.finditer(r"[^\n]+", text[heading.end() : end.start()])
    ]
    if heading.group("cities"):
        lines.insert(0, (heading.group("cities"), heading.start("cities")))
    for line, offset in lines:
        value = line.strip()
        fields = _LOCATION_LINE.fullmatch(value)
        if not fields:
            continue
        for city in re.finditer(_CITY, fields["locations"]):
            start = offset + len(line) - len(line.lstrip()) + city.start()
            if city[0] not in {item["value"] for item in result}:
                result.append(
                    {
                        "value": city[0],
                        "source_kind": "body",
                        "source_text": city[0],
                        "start_char": start,
                        "end_char": start + len(city[0]),
                    }
                )
    return result


def effective_job_locations(job) -> list[str]:
    """Read-through repair for old saved jobs; never overwrites stored metadata."""
    return location_field_values(list(job.locations or [])) or [
        item["value"]
        for item in header_location_evidence(job.raw_content or "", job.title)
    ]


def recruitment_type_conflicts(job) -> list[str]:
    """Find explicit current-job type conflicts, not past internship experience."""
    text = job.raw_content or ""
    if job.job_type in {"campus", "full_time"}:
        from src.services.job_role_review import duty_text

        quotes = []
        if re.search(r"实习|\bintern(?:ship)?\b", job.title or "", re.IGNORECASE):
            quotes.append(job.title)
        for source, pattern in (
            (
                duty_text(job),
                r"实习(?:内容|职责|工作|岗位)|\binternship (?:duties|role)\b",
            ),
            (text, r"实习周期|连续实习\s*\d|(?:每周|每星期)(?:可)?实习\s*\d|至少实习"),
        ):
            quotes.extend(
                s.strip()
                for s in re.split(r"[。；;\n]", source)
                if re.search(pattern, s, re.IGNORECASE)
            )
        return list(dict.fromkeys(quotes))[:3]
    if job.job_type == "internship":
        # Conversion opportunities in duties do not make an internship formal.
        end = _HEADER_END.search(text)
        header = text[: end.start()] if end else ""
        return [
            line.strip()
            for line in header.splitlines()
            if re.fullmatch(
                r"(?:招聘类型\s*[：:]\s*)?(?:正式|正式校招|全职|社会招聘|社招)",
                line.strip(),
            )
        ][:3]
    return []
