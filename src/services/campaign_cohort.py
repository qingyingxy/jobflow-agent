"""Distinguish the user's target cohort from graduation evidence on a page."""
import re


def cohort_status(text, year):
    text = re.sub(r"\s+", "", text)
    if re.search(rf"(?:不接受|不招收|不面向|不含|不包括)[^。；;]{{0,12}}(?:{year}|{year % 100})届", text):
        return "excluded"
    years = [2000 + int(v) for v in re.findall(r"(?<!\d)(?:20)?(\d{2})届", text)]
    # A graduation range, never the publication or application window.
    for match in re.finditer(r"(20\d{2})年?(?:\d{1,2}月(?:\d{1,2}日)?)?[—–~～至到-]+(20\d{2})年?(?:\d{1,2}月(?:\d{1,2}日)?)?[^。；;]{0,16}毕业", text):
        first, last = map(int, match.group(1, 2))
        if first <= year <= last:
            return "confirmed"
        years.extend([first, last])
    for match in re.finditer(r"(20\d{2})年(?:及以后|及之后|以后|之后|起)[^。；;]{0,12}毕业", text):
        if year >= int(match[1]):
            return "confirmed"
        years.append(int(match[1]))
    years.extend(int(v) for v in re.findall(r"(20\d{2})年(?:\d{1,2}月(?:\d{1,2}日)?)?(?:的|应届|预计|即将|正式)*毕业", text))
    years.extend(int(v) for v in re.findall(r"毕业(?:年份|时间|年度)[：:]?(20\d{2})", text))
    return "confirmed" if year in years else "excluded" if years else "unspecified"


def relevant_campaign_text(text, limit=22000):
    """Keep original excerpts from long pages, including application facts near the end."""
    if len(text) <= limit:
        return text
    ranges = [(0, 2500)]
    markers = r"招聘对象|毕业时间|毕业年份|网申时间|报名时间|投递时间|应届投递|网申截止|投递须知|岗位职责|任职要求"
    for match in re.finditer(markers, text):
        start, end = max(0, match.start() - 1000), min(len(text), match.end() + 2400)
        if any(a <= start and end <= b for a, b in ranges):
            continue
        ranges.append((start, end))
        if sum(b - a for a, b in ranges) >= limit - 3500:
            break
    ranges.append((max(0, len(text) - 2500), len(text)))
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return "\n[下一个原文片段，不能拼接引用]\n".join(text[a:b] for a, b in merged)[:limit]
