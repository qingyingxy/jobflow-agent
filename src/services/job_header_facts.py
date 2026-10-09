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
_CITY = r"(?:" + "|".join(map(re.escape, _CITIES)) + r")(?:市)?"
_LOCATION_LINE = re.compile(
    rf"{_CITY}(?:\s*[/、,，|]\s*{_CITY})*"
    r"(?:[ \t]+(?:校招|校园招聘|社招|社会招聘|实习|实习生|全职|兼职))?"
)


def header_location_evidence(text: str, title: str | None) -> list[dict]:
    """Require an exact title line and a bounded header ending at JD sections.

    The whole line must be city fields plus an optional recruitment-type label.
    Thus company introductions, references
    to other cities in duties, and partially understood lists cannot prove a
    work location. HTML navigation/related jobs must already be scoped out.
    """
    if not title:
        return []
    heading = re.search(rf"(?m)^[ \t]*{re.escape(title.strip())}[ \t]*$", text)
    end = _HEADER_END.search(text, heading.end()) if heading else None
    if not heading or not end or end.start() - heading.end() > 1200:
        return []
    result = []
    for line in re.finditer(r"[^\n]+", text[heading.end() : end.start()]):
        value = line[0].strip()
        if not _LOCATION_LINE.fullmatch(value):
            continue
        for city in re.finditer(_CITY, line[0]):
            start = heading.end() + line.start() + city.start()
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
    return list(job.locations or []) or [
        item["value"]
        for item in header_location_evidence(job.raw_content or "", job.title)
    ]
