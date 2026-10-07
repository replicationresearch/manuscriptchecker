"""Review code files found via repo_check for common reproducibility red flags.

For each code file (under a size cap), fetches the raw content from GitHub and
runs a handful of cheap, language-aware heuristics: comment density, hardcoded
local/absolute file paths (a common "works on my machine" reproducibility
break), and - for R/Python scripts that call a randomization function -
whether a random seed is set anywhere in the file. This is not a full static
analyser; it flags things worth a human look, not correctness.
"""

import re

import pandas as pd
import requests

from .registry import register, module_output, md_table
from .._log import logger

MAX_FILES_TO_FETCH = 25
MAX_FILE_BYTES = 300_000
FETCH_TIMEOUT = 10

COMMENT_PREFIX = {"R": "#", "R Markdown": "#", "Python": "#", "Stata": "*"}
RANDOM_FN = {
    "R": r"\b(sample|rnorm|runif|rbinom|rpois|sample\.int)\s*\(",
    "Python": r"\b(random\.\w+|np\.random\.\w+|numpy\.random\.\w+)\s*\(",
}
SEED_FN = {
    "R": r"\bset\.seed\s*\(",
    "Python": r"\b(random\.seed|np\.random\.seed|numpy\.random\.seed)\s*\(",
}
# Windows drive-letter paths, or /Users/.../  /home/.../  paths, or ~-relative.
ABS_PATH_RE = re.compile(
    r"[A-Za-z]:[\\/][^\s\"')]+|/(?:Users|home)/[A-Za-z0-9_.\-]+[^\s\"')]*|~[\\/][^\s\"')]*")


def _lang(name):
    ext = name.lower().rsplit(".", 1)[-1]
    return {"r": "R", "rmd": "R Markdown", "py": "Python", "sas": "SAS",
            "do": "Stata", "spss": "SPSS", "jasp": "JASP"}.get(ext, "Other")


def _raw_url(file_url):
    """github.com/.../blob/HEAD/path -> raw.githubusercontent.com/.../HEAD/path."""
    return (file_url or "").replace("github.com", "raw.githubusercontent.com") \
                           .replace("/blob/", "/")


def _fetch(file_url):
    url = _raw_url(file_url)
    if not url:
        return None
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT,
                         headers={"User-Agent": "chetameck"})
        if r.status_code == 200 and len(r.content) <= MAX_FILE_BYTES:
            return r.text
    except Exception as e:  # noqa: BLE001
        logger.debug("code_check: could not fetch %s: %s", url, e)
    return None


def _review(language, content):
    lines = content.splitlines()
    prefix = COMMENT_PREFIX.get(language)
    n_comments = (sum(1 for l in lines if l.strip().startswith(prefix))
                  if prefix else None)
    abs_paths = len(ABS_PATH_RE.findall(content))
    issues = []
    if abs_paths:
        issues.append(f"{abs_paths} hardcoded local/absolute path(s)")
    random_pat = RANDOM_FN.get(language)
    seed_pat = SEED_FN.get(language)
    if random_pat and re.search(random_pat, content) and not (
            seed_pat and re.search(seed_pat, content)):
        issues.append("uses randomization without visibly setting a seed")
    return len(lines), n_comments, issues


@register("code_check")
def code_check(paper, prev_outputs=None):
    prev = prev_outputs or {}
    repo = prev.get("repo_check", {})
    files = repo.get("table") if isinstance(repo, dict) else None
    if files is None or files.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No code files to review.",
            report=["No code files were found to review."], na_replace=0)

    code_files = [f for _, f in files.iterrows()
                 if re.search(r"\.(r|rmd|py|sas|do|stata|spss|jasp)$",
                              str(f.get("file_name", "")), re.I)]
    if not code_files:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No code files detected.",
            report=["No code files detected."], na_replace=0)

    rows = []
    n_fetched = 0
    for f in code_files:
        name = str(f.get("file_name", ""))
        file_url = f.get("file_url", "")
        language = _lang(name)
        row = {"file_name": name, "language": language, "checked": False,
              "code_lines": None, "comment_lines": None, "issues": ""}
        if n_fetched < MAX_FILES_TO_FETCH:
            n_fetched += 1
            content = _fetch(file_url)
            if content is not None:
                n_lines, n_comments, issues = _review(language, content)
                row.update({"checked": True, "code_lines": n_lines,
                           "comment_lines": n_comments,
                           "issues": "; ".join(issues) if issues else "-"})
        rows.append(row)

    table = pd.DataFrame(rows)
    n = len(table)
    n_checked = int(table["checked"].sum())
    n_with_issues = int(((table["issues"] != "") & (table["issues"] != "-")).sum())
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "code_n": [n],
                            "code_checked": [n_checked], "code_issues": [n_with_issues]})
    tl = "yellow" if n_with_issues else ("info" if n_checked else "na")

    note = (f"{n_checked} of {n} content-checked" if n_checked < n else
           f"all {n} content-checked")
    report = [f"{n} code file{'s' if n != 1 else ''} found ({note}; larger or "
             "unreachable files are listed but not reviewed)."]
    report.append(md_table(table, ["file_name", "language", "code_lines",
                                   "comment_lines", "issues"],
                           ["File", "Language", "Lines", "Comment lines", "Notes"]))
    summary_text = (f"{n} code file(s), {n_with_issues} with a potential issue."
                    if n_checked else f"{n} code file(s) found.")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
