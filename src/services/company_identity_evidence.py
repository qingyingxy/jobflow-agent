"""Interpret explicit company identity evidence without inventing source URLs."""
import re
from urllib.parse import urlsplit


def company_names(company):
    # Mixed Chinese/English brand labels are alternatives, not one exact token.
    values = [company.strip()]
    parts = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z][a-zA-Z0-9]*(?:[ .-]+[a-zA-Z][a-zA-Z0-9]*)*", company)
    if len(parts) > 1:
        values.extend(p.strip() for p in parts if len(p.strip()) >= 2)
    if re.search(r"\s+AI$", company, re.IGNORECASE):
        values.append(re.sub(r"\s+AI$", "", company, flags=re.IGNORECASE))
    return tuple(dict.fromkeys(v for v in values if v.casefold() not in {
        "ai", "科技", "智能", "公司", "集团", "中国", "technology", "group", "inc", "ltd"}))


def company_name_matches(company, text):
    return any(re.search((r"(?<![a-zA-Z0-9])" if name[0].isascii() else "") + re.escape(name)
                         + (r"(?![a-zA-Z0-9])" if name[-1].isascii() else ""), text, re.IGNORECASE)
               for name in company_names(company))


def homepage_declarations(page, company, candidate, observed_urls=()):
    """Return a home and the exact observation that supports it.

    Labeled text URLs count as text declarations, never fabricated hyperlinks.
    Bare domains may only select root URLs already observed on readable pages.
    PDF annotations retain the existing hyperlink-only policy.
    """
    from src.services.company_discovery import home_url, host, under_domain

    if not company_name_matches(company, page["text"]):
        return []
    result = []
    for link in page["links"]:
        target = home_url(link.url)
        named = company_name_matches(company, link.text)
        official = bool(re.search(r"(?:公司)?官网|官方网站|official website|^website$|homepage", link.text, re.IGNORECASE))
        related = target and under_domain(host(candidate), host(target))
        if target and (related or named or official) and (named or company_name_matches(company, page["title"]) or (official and related)):
            result.append({"url": target, "observation": "hyperlink", "quote": link.text[:400], "source_url": page["url"]})
    if page.get("method") == "pdf":
        return result
    text = page["text"]
    for match in re.finditer(r"https?://[^\s<>\"'\u4e00-\u9fff，。；）】]+", text):
        before = text[max(0, match.start() - 50):match.start()]
        label = re.search(r"(?:公司官网|官方网站|公司网址|企业官网|官网(?:地址|链接)?|official website)\s*[:：]?\s*$", before, re.IGNORECASE)
        target = home_url(match.group().rstrip(".,;:，。；：)】]"))
        if (label and target and under_domain(host(candidate), host(target))
                and not re.search(r"非官方|假冒|仿冒|钓鱼|不是官网|非官网|示例", before[max(0, label.start() - 12):], re.IGNORECASE)):
            result.append({"url": target, "observation": "labeled_text_url", "quote": before[label.start():] + match.group(), "source_url": page["url"]})
    # E.g. a government notice explicitly names the official domain. We only
    # choose a URL already seen, and do not turn arbitrary text into navigation.
    for match in re.finditer(r"官网(?:域名)?\s*(?:仅认准|为|是|[:：])\s*[\"“]?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", text):
        if re.search(r"非官方|假冒|仿冒|钓鱼|不是|非|示例", text[max(0, match.start() - 12):match.start()], re.IGNORECASE):
            continue
        domain = match.group(1).lower().removeprefix("www.")
        if not under_domain(host(candidate), domain):
            continue
        for url in observed_urls:
            if host(url) == domain and urlsplit(url).path in {"", "/"} and (target := home_url(url)):
                result.append({"url": target, "observation": "explicit_domain", "quote": match.group(), "source_url": page["url"]})
                break
    return result
