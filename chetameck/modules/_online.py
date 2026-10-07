"""Shared helpers for online (network) modules."""

import re

import requests

from ..text import text_search
from .._log import logger

# The OSF guid used in metacheck's own documentation/example manuscripts; it
# shows up in template text copy-pasted into real papers and would otherwise
# be (falsely) flagged as the paper's own supplementary-materials link.
_OSF_DOC_EXAMPLE_GUID = "tvyxz"


def get_links(paper, pattern):
    """Return unique URLs in the text matching a regex pattern."""
    urls = text_search(paper, pattern, return_type="match", perl=True)
    out = []
    for u in (urls["text"].tolist() if not urls.empty else []):
        # drop trailing punctuation that is not part of the URL
        u = re.sub(r"[.,;:)\]}<>]+$", "", str(u)).strip()
        if u:
            out.append(u)
    return list(dict.fromkeys(out))


def github_links(paper):
    urls = get_links(paper, r"https?://(?:www\.)?github\.com/[^\s]+")
    # text mentions of "github ... repo"
    hits = text_search(paper, r"github", return_type="sentence")
    if not hits.empty:
        for t in hits["text"]:
            if re.search(r"repo", t, re.I):
                m = re.search(r"https?://github\.com/[^\s]+", t)
                if m:
                    urls.append(m.group(0))
    return list(dict.fromkeys(urls))


def osf_links(paper):
    urls = get_links(paper, r"https?://(?:www\.)?osf\.io/[^\s]+")
    urls = [u for u in urls if _OSF_DOC_EXAMPLE_GUID not in u]
    return list(dict.fromkeys(urls))


# Human-readable labels for the OSF API `type` field.
OSF_TYPE_LABEL = {
    "nodes": "Project",
    "registrations": "Registration",
    "files": "File",
    "preprints": "Preprint",
    "users": "User",
    "components": "Component",
}


def osf_link_info(url):
    """Resolve an OSF link to what it actually is, using the OSF API.

    OSF GUIDs are 5-char ids; waterbutler/file ids are 24-char. We query the
    relevant endpoint and return the object's type (nodes/registrations/files/
    preprints/users) and its title/name. Best effort: on any failure we return
    ``osf_type`` = "unknown".
    """
    m = re.search(r"osf\.io/([A-Za-z0-9]+)", url)
    if not m:
        return {"link": url, "osf_type": "unknown", "title": ""}
    oid = m.group(1)
    api = "https://api.osf.io/v2"
    headers = {"Accept": "application/vnd.api+json", "User-Agent": "metacheck"}
    try:
        if len(oid) == 5:
            r = requests.get(f"{api}/guids/{oid}/", headers=headers, timeout=15)
        else:
            r = requests.get(f"{api}/files/{oid}/", headers=headers, timeout=15)
        if r.status_code == 404:
            return {"link": url, "osf_type": "unfound", "title": ""}
        if r.status_code in (401, 403):
            return {"link": url, "osf_type": "private", "title": ""}
        if r.status_code != 200:
            return {"link": url, "osf_type": "unavailable", "title": ""}
        data = r.json().get("data", {})
        att = data.get("attributes", {})
        typ = data.get("type", "")
        title = (att.get("title") or att.get("name")
                 or att.get("full_name") or "")
        return {"link": url, "osf_type": typ, "title": title}
    except Exception as e:  # noqa: BLE001
        logger.debug("osf_link_info: failed to resolve %s: %s", url, e)
        return {"link": url, "osf_type": "unknown", "title": ""}


def zenodo_links(paper):
    urls = get_links(paper, r"https?://(?:www\.)?zenodo\.org/[^\s]+")
    return list(dict.fromkeys(urls))


def rbox_links(paper):
    urls = get_links(paper, r"https?://(?:www\.)?researchbox\.org/[^\s]+")
    return list(dict.fromkeys(urls))


def aspredicted_links(paper):
    urls = get_links(paper, r"https?://(?:www\.)?aspredicted\.org/[^\s]+")
    return list(dict.fromkeys(urls))


def github_files(repo_url):
    """List files in a GitHub repo (best effort via the GitHub API)."""
    m = re.search(r"github\.com/([^/]+)/([^/]+)", repo_url)
    if not m:
        return []
    owner, repo = m.group(1), m.group(2)
    api = f"https://api.github.com/repos/{owner}/{repo}/git/trees/HEAD?recursive=1"
    try:
        r = requests.get(api, timeout=20)
        if r.status_code != 200:
            return []
        data = r.json()
        out = []
        for item in data.get("tree", []):
            if item.get("type") == "blob":
                out.append({
                    "file_name": item["path"].split("/")[-1],
                    "file_url": f"https://github.com/{owner}/{repo}/blob/HEAD/{item['path']}",
                    "file_location": item["path"],
                    "file_size": item.get("size"),
                    "file_type": _classify_file(item["path"]),
                })
        return out
    except Exception as e:  # noqa: BLE001
        logger.debug("github_files: failed to list %s: %s", repo_url, e)
        return []


def _classify_file(name):
    low = name.lower()
    if low.endswith((".zip", ".tar", ".gz", ".7z", ".rar")):
        return "archive"
    if low.endswith((".r", ".rmd", ".py", ".sas", ".do", ".stata", ".spss", ".jasp")):
        return "code"
    if low.startswith("readme") or low.endswith(".md"):
        return "readme"
    if low.endswith((".csv", ".tsv", ".xlsx", ".xls", ".sav", ".dta", ".json", ".rds")):
        return "data"
    return "other"
