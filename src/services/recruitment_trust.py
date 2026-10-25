"""URL-scoped evidence for an official site's outbound hiring link."""

import re
from urllib.parse import urlsplit

ATS_DOMAINS = ("mokahr.com", "zhiye.com", "hotjob.cn", "recruitment.hrtps.com", "jobs.feishu.cn", "jobs.f.mioffice.cn")


def ats_jobs_route(url):
    """An observed ATS jobs fragment, including public /apply tenant portals."""
    parsed = urlsplit(url)
    return bool(hiring_scope(url) and re.match(r"^/?jobs?(?:/|\?|$)", parsed.fragment, re.IGNORECASE))


def hiring_scope(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if not any(host == root or host.endswith("." + root) for root in ATS_DOMAINS):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    # Shared portal: the first path segment binds one employer tenant.
    if host == "wecruit.hotjob.cn":
        return (host, "/" + parts[0] + "/") if parts and parts[0].startswith("SU") and parts[0][2:].isalnum() else None
    # Legacy Hotjob portals also bind an employer in /wt/<tenant>/.
    # The shared /wt/ root and other employer paths confer no trust.
    if host in {"hotjob.cn", "www.hotjob.cn"}:
        return (host, "/wt/" + parts[1] + "/") if (
            len(parts) >= 3 and parts[0] == "wt" and re.fullmatch(r"[a-zA-Z0-9_-]+", parts[1])
        ) else None
    # A shared ATS host is never globally trusted. Moka's first two path
    # segments identify a tenant (e.g. /social-recruitment/acme/...).
    if host in {"mokahr.com", "www.mokahr.com", "app.mokahr.com"}:
        # /m/ is a mobile presentation prefix, never the employer identifier.
        width = 3 if parts and parts[0] == "m" else 2
        return (host, "/" + "/".join(parts[:width]) + "/") if len(parts) >= width else None
    if any(host == root or host == "www." + root for root in ATS_DOMAINS):
        return None
    return host, "/"  # enterprise-specific ATS subdomain


def within_scope(url, scope):
    parsed = urlsplit(url)
    return parsed.hostname == scope[0] and (parsed.path.rstrip("/") + "/").startswith(
        scope[1]
    )
