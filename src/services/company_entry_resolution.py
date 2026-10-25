"""Follow bounded, observed ownership and hiring links; never guess career URLs."""

import re
from urllib.parse import urlsplit

from src.services.company_discovery import (
    NON_COMPANY_ROOTS,
    RECRUITMENT,
    clean_url,
    host,
    same_url,
    under_domain,
)
from src.services.company_identity_evidence import company_name_matches
from src.services.recruitment_trust import ATS_DOMAINS, hiring_scope, within_scope

ABOUT = re.compile(r"关于|公司介绍|企业介绍|了解我们|about|company", re.IGNORECASE)
DETAIL = re.compile(r"/(?:job|position|jobs|positions)/[^/]+(?:/detail)?/?$", re.IGNORECASE)


def permitted_entry(url):
    if not clean_url(url):
        return False
    if any(under_domain(host(url), root) for root in ATS_DOMAINS):
        return hiring_scope(url) is not None
    return not any(under_domain(host(url), root) for root in NON_COMPANY_ROOTS)


def within_redirect(url, requested, homepage):
    scope = hiring_scope(requested)
    if scope:
        return within_scope(url, scope)
    return host(url) == host(requested) or (
        under_domain(host(requested), host(homepage)) and under_domain(host(url), host(homepage))
    )


async def resolve_company_entry(agent, row, homepage):
    """At most four linked pages / three edges, plus one existing browser slot."""
    # Observed local-language recruitment pages on the corroborated exact host
    # can carry the hiring link even when its global landing page cannot.
    related = {p["url"]: p for p in agent.pages.values() if host(p["url"]) == host(row.homepage_url)
               and company_name_matches(row.company, p["text"])}
    queue = [(homepage, []), *((p, []) for p in related.values() if p["url"] != homepage["url"])]
    visited, fetched = set(), 0
    suggested = row.career_url
    from src.services.discovery_matching import search_filter_conditions
    from src.services.lead_presentation import discovery_kind
    from src.services.recruitment_listing import recruitment_priority

    types = search_filter_conditions(agent.query)["job_types"]
    fallback = None
    while queue:
        page, chain = queue.pop(0)
        if page["url"] in visited:
            continue
        visited.add(page["url"])
        if len(chain) >= 3:
            continue
        # An independently corroborated root may itself be the campus site.
        # It needs a real recruitment body, not just a title/JS shell, and does
        # not need to link to a second recruitment site to establish its entry.
        if (not chain and host(page["url"]) == host(row.homepage_url)
                and company_name_matches(row.company, page["title"])
                and RECRUITMENT.search(page["title"])
                and (discovery_kind(page["url"], page["title"], observed_title=True) != "job"
                     or re.search(r"招聘公告|招聘简章|校园招聘专题", page["title"]))
                and len(page["text"].strip()) > len(page["title"].strip()) + 60):
            fallback = page, [agent.proof(page, linked_url=page["url"], final_url=page["url"],
                link_text="已核验的公司招聘页面", relation="corroborated_recruitment_page")]
        links = sorted(page["links"], key=lambda link: (
            not bool(RECRUITMENT.search(link.text + " " + link.url)),
            recruitment_priority(link, types),
            not same_url(link.url, suggested),
        ))
        usable = [link for link in links if permitted_entry(link.url) and (
            RECRUITMENT.search(link.text + " " + urlsplit(link.url).path + " " + host(link.url))
            or ABOUT.search(link.text + " " + urlsplit(link.url).path)
        )]
        if not usable and page.get("method") == "http" and agent.evidence_reader.browser_remaining:
            rendered = await agent.read(page["url"], force_browser=True)
            if rendered and rendered.get("method") == "browser" and host(rendered["url"]) == host(page["url"]):
                visited.remove(page["url"])
                queue.insert(0, (rendered, chain))
                continue
        for link in usable:
            is_hiring = bool(RECRUITMENT.search(link.text + " " + urlsplit(link.url).path + " " + host(link.url)))
            if not same_url(link.url, suggested) and DETAIL.search(urlsplit(link.url).path):
                continue
            if link.url in visited:
                continue
            # Agent-selected supplemental reads remain useful after the network
            # budget is spent, but still need a real official outbound edge.
            if link.url not in agent.pages:
                if fetched >= 4:
                    continue
                fetched += 1
            target = await agent.read(link.url)
            if not target or not within_redirect(target["url"], link.url, row.homepage_url):
                continue
            cross_domain = not under_domain(host(target["url"]), host(row.homepage_url))
            ats = hiring_scope(link.url)
            # A separate domain must name this brand in its title, or mention
            # it in the body and link back to the corroborated site.
            reciprocal = any(host(back.url) == host(row.homepage_url) for back in target["links"])
            branded = company_name_matches(row.company, target["title"])
            if cross_domain and not ats and not (branded or (
                    company_name_matches(row.company, target["text"]) and reciprocal)):
                continue
            edge = agent.proof(page, linked_url=link.url, final_url=target["url"],
                               link_text=link.text[:300], relation="hiring" if is_hiring else "company")
            next_chain = [*chain, edge]
            if is_hiring and RECRUITMENT.search(target["title"] + " " + target["text"]):
                if recruitment_priority(link, types) > 0 and any(
                    recruitment_priority(child, types) == 0 and permitted_entry(child.url)
                    for child in target["links"]
                ):
                    fallback = target, next_chain
                    queue.insert(0, (target, next_chain))
                    break
                return target, next_chain
            if not ats:
                queue.append((target, next_chain))
        # If a page explicitly linked as a hiring page now loads an empty
        # shell, it is not upgraded based on URL words alone.
    # A corroborated company root can also own a branded recruitment subdomain
    # whose visible return link points back to that root. The link direction is
    # recorded honestly; no nonexistent homepage -> careers edge is fabricated.
    if (suggested not in visited and not hiring_scope(suggested)
            and host(suggested) != host(row.homepage_url)
            and under_domain(host(suggested), host(row.homepage_url))):
        target = await agent.read(suggested)
        back = next((link for link in (target or {}).get("links", [])
                     if host(link.url) == host(row.homepage_url)), None)
        if (target and within_redirect(target["url"], suggested, row.homepage_url)
                and back and company_name_matches(row.company, target["title"])
                and RECRUITMENT.search(target["title"] + " " + target["text"])):
            return target, [agent.proof(target, linked_url=back.url, final_url=homepage["url"],
                link_text=back.text[:300], relation="same_domain_return_to_homepage")]
    return fallback
