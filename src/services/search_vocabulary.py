"""Shared aliases; unknown user-entered values remain valid values."""

from src.services.job_header_facts import _CITIES

_LOCATION_GROUPS: tuple[tuple[str, ...], ...] = (
    ("北京", "beijing"),
    ("上海", "shanghai"),
    ("深圳", "shenzhen"),
    ("广州", "guangzhou"),
    ("杭州", "hangzhou"),
    ("成都", "chengdu"),
    ("南京", "nanjing"),
    ("武汉", "wuhan"),
    ("苏州", "suzhou"),
    ("西安", "xi'an", "xian"),
    ("天津", "tianjin"),
    ("重庆", "chongqing"),
    ("厦门", "xiamen"),
    ("新加坡", "singapore"),
    ("香港", "hong kong"),
    ("圣何塞", "san jose"),
    ("西雅图", "seattle"),
)

_ROLE_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (
        ("ai应用", "ai 应用", "人工智能应用"),
        ("ai应用", "ai 应用", "人工智能应用", "agent", "智能体", "rag", "大模型"),
    ),
    (("agent", "智能体"), ("agent", "智能体")),
    (
        ("llm", "大模型", "大语言模型", "large language model"),
        (
            "llm",
            "大模型",
            "大语言模型",
            "large language model",
            "foundation model",
            "generative ai",
        ),
    ),
    (
        ("算法", "algorithm"),
        (
            "算法",
            "algorithm",
            "machine learning",
            "机器学习",
            "deep learning",
            "深度学习",
            "推荐",
            "搜索",
            "计算机视觉",
        ),
    ),
    (("rag", "检索增强"), ("rag", "检索增强")),
    (("nlp", "自然语言处理"), ("nlp", "自然语言处理")),
    (("计算机视觉", "computer vision", "cv"), ("计算机视觉", "computer vision", "cv")),
    (("数据", "data"), ("数据", "data")),
    (("后端", "backend", "back-end"), ("后端", "backend", "back-end")),
    (("前端", "frontend", "front-end"), ("前端", "frontend", "front-end")),
    (("测试", "qa"), ("测试", "quality assurance", "qa")),
    (("产品", "product"), ("产品", "product")),
)


# Header extraction and intent parsing use the same city coverage.
_LOCATION_GROUPS += tuple(
    (city,) for city in _CITIES if not any(city in group for group in _LOCATION_GROUPS)
)


def canonical_location(value):
    value = value.strip().casefold()
    for group in _LOCATION_GROUPS:
        if value in group or value.removesuffix("市") in group:
            return group[0]
    return value


def location_aliases(value):
    value = canonical_location(value)
    return next((g for g in _LOCATION_GROUPS if g[0] == value), (value,))


def canonical_role(value):
    value = value.strip().casefold()
    if value in {"ai", "人工智能", "artificial intelligence"}:
        return "ai"
    return next((aliases[0] for aliases, _ in _ROLE_GROUPS if value in aliases), value)
