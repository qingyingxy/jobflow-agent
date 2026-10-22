"""Identity hints for entrances reached from an already trusted employer page.

These hints never create official trust from an arbitrary search result.
The caller still verifies the actual outbound link and redirect/tenant scope.
"""
import re
from urllib.parse import urlsplit


def entry_brand_matches(company, title, *, official_url=None):
    from src.services.company_discovery import mentions

    if mentions(company, title):
        return True
    # Legal/organisational suffixes vary between the company and careers site.
    def stem(value):
        return re.sub(r"(?:股份有限公司|有限责任公司|有限公司|集团|汽车|科技|公司)+$", "", value.strip())

    name = stem(company)
    if (len(name) >= 2 and name != company and re.search(r"[\u4e00-\u9fff]", name)
            and re.search(re.escape(name) + r"(?:集团|汽车|科技|公司|招聘|校招|官网|$)", title)):
        return True
    # An English brand can be evidenced by the trusted employer's own domain.
    # Do not take the brand from the untrusted destination's hostname.
    if official_url:
        labels = (urlsplit(official_url).hostname or "").lower().split(".")
        ignored = {"www", "jobs", "job", "career", "careers", "recruit", "campus", "com", "cn", "net", "org", "co"}
        return any(len(label) >= 4 and label not in ignored and label.isalpha()
                   and re.search(r"(?<![a-z0-9])" + re.escape(label) + r"(?![a-z0-9])", title, re.IGNORECASE)
                   for label in labels[:-1])
    return False
