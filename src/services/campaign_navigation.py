"""Rank observed recruitment navigation without employer-specific routes."""
import re
from urllib.parse import parse_qsl, unquote, urlsplit

from src.services.campaign_cohort import cohort_status
from src.services.lead_presentation import discovery_kind, reference_link_reason
from src.services.recruitment_trust import ats_jobs_route, hiring_scope

CAMPUS = re.compile(r"校招|校园|应届|秋招|毕业生|campus|graduate|university|school|/edu(?:/|$)", re.IGNORECASE)
HIRING = re.compile(r"招聘|校招|秋招|补招|补录|提前批|应届|职位|岗位|投递|加入我们|careers?|jobs?|positions?", re.IGNORECASE)
EXCLUDED = re.compile(
    r"社会招聘|社招|实习|春招|春季招聘|个人中心|我的申请|我的投递|投递记录|申请记录|简历中心|登录|注册"
    r"|/(?:social|experienced|intern|internship)(?:[-_/?.#]|$)"
    r"|/(?:login|signin|register|personal|account|resume)(?:[/?#.]|$)"
    r"|[?&]recruitType=INTERN(?:&|$)", re.IGNORECASE)
UNRELATED = re.compile(r"/(?:legal|privacy|cookies?|policy|terms|investor_relations|contact|certificates)(?:[-_/?.]|$)", re.IGNORECASE)


def job_filter_url(url):
    """A keyword-filtered job list is an availability lead, not another recruitment batch."""
    parsed = urlsplit(url)
    route = urlsplit(parsed.fragment.removeprefix("!"))
    return any(key.casefold() in {"keyword", "keywords", "searchkeyword", "searchtext"} and value.strip()
               for key, value in parse_qsl(parsed.query) + parse_qsl(route.query))


def announcement_link(url, label=""):
    return bool(re.search(r"(?:校招|招聘|秋招|补录|补招)(?:公告|简章)|(?:校招|校园招聘|管培生).*(?:启动|开启)", label)
                or re.search(r"/(?:announcements?|notices?)(?:/|$)", urlsplit(url).path, re.IGNORECASE))


def navigation_candidate(url, label, year=None, *, observed=True):
    """Return (priority, entry) for a candidate; this never grants URL trust."""
    parsed = urlsplit(url)
    route = unquote(parsed.path + "?" + parsed.query + "#" + parsed.fragment)
    if (EXCLUDED.search(label + " " + route) or UNRELATED.search(route)
            or re.search(r"隐私政策|隐私声明|服务协议|用户协议|作品提交", label + " " + route, re.IGNORECASE)):
        return None
    if year is not None and cohort_status(label, year) == "excluded":
        return None
    if announcement_link(url, label):
        return (4, False)
    reference = reference_link_reason(url)
    if not observed and re.search(r"/(?:notices?|announcements?)(?:[/.?#]|$)", route, re.IGNORECASE):
        return (4, False)
    if reference and reference not in {"article_or_discussion", "attachment_or_document", "help_or_support_page"}:
        return None
    if reference:
        # Footer links cannot turn corporate news, old PDFs or products into recruitment.
        if not re.search(r"校招|校园招聘|应届|秋招|招聘公告|招聘简章|投递须知|招聘流程", label):
            return None
        return (8 if re.search(r"须知|流程|FAQ|常见问题", label, re.IGNORECASE) else 4, False)
    job = discovery_kind(url, label if observed and len(label) <= 250 else None, observed_title=observed) == "job"
    campus_route = bool(CAMPUS.search(route))
    ats = bool(hiring_scope(url))
    if job:
        # A bare short /p/ route also occurs on social profiles and product pages.
        if re.search(r"/p/", parsed.path, re.IGNORECASE) and not label.strip() and not ats:
            return None
        return (0, True)
    if ats_jobs_route(url) or (ats and campus_route):
        return (1, True)
    if re.search(r"常见问题|须知|流程|FAQ", label, re.IGNORECASE):
        return (8, False) if HIRING.search(label) else None
    if not HIRING.search(label) and not (campus_route and re.search(r"/(?:campus|school|graduate|university|edu)(?:[-_/?.#]|$)", route, re.IGNORECASE)):
        return None
    if re.search(r"公告|简章|新闻|宣讲", label):
        return (4, False)
    entry = bool(ats or re.search(r"职位|岗位|投递|申请|/jobs?(?:[/?#]|$)|/positions?(?:[/?#]|$)", label + " " + route, re.IGNORECASE))
    return (1 if entry else 2 if CAMPUS.search(label) or campus_route else 3, entry)


def irrelevant_document(page, year):
    """Reject explicit wrong cohorts/types in the page header, not its navigation."""
    title = page.get("title", "")
    return bool(EXCLUDED.search(title) or
                (re.search(r"大赛|竞赛|赛事|作品提交", title) and not re.search(r"招聘|校招", title)) or
                (re.search(r"校招|校园招聘|招聘简章", title) and cohort_status(title, year) == "excluded"))
