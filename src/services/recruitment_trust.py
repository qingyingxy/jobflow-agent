"""URL-scoped evidence for an official site's outbound hiring link."""

from urllib.parse import urlsplit

ATS_DOMAINS = ("mokahr.com", "zhiye.com", "hotjob.cn", "recruitment.hrtps.com", "jobs.feishu.cn", "jobs.f.mioffice.cn")


def hiring_scope(url):
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if not any(host == root or host.endswith("." + root) for root in ATS_DOMAINS):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    # A shared ATS host is never globally trusted. Moka's first two path
    # segments identify a tenant (e.g. /social-recruitment/acme/...).
    if host in {"mokahr.com", "www.mokahr.com", "app.mokahr.com"}:
        return (host, "/" + "/".join(parts[:2]) + "/") if len(parts) >= 2 else None
    if any(host == root or host == "www." + root for root in ATS_DOMAINS):
        return None
    return host, "/"  # enterprise-specific ATS subdomain


def within_scope(url, scope):
    parsed = urlsplit(url)
    return parsed.hostname == scope[0] and (parsed.path.rstrip("/") + "/").startswith(
        scope[1]
    )
