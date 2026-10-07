"""List files on OSF / GitHub / ResearchBox / Zenodo repos referenced in paper."""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search
from ._online import (github_links, osf_links, zenodo_links, rbox_links,
                      github_files, _classify_file)


@register("repo_check")
def repo_check(paper, prev_outputs=None):
    repos = []
    for u in github_links(paper):
        repos.append({"repo_url": u, "repo_type": "github"})
    for u in osf_links(paper):
        repos.append({"repo_url": u, "repo_type": "osf"})
    for u in zenodo_links(paper):
        repos.append({"repo_url": u, "repo_type": "zenodo"})
    for u in rbox_links(paper):
        repos.append({"repo_url": u, "repo_type": "researchbox"})

    # dedupe
    seen = set()
    unique = []
    for r in repos:
        if r["repo_url"] not in seen:
            seen.add(r["repo_url"])
            unique.append(r)

    all_files = []
    for r in unique:
        if r["repo_type"] == "github":
            for f in github_files(r["repo_url"]):
                f["repo_url"] = r["repo_url"]
                all_files.append(f)

    table = pd.DataFrame(all_files) if all_files else pd.DataFrame()
    n_repo = len(unique)
    if not table.empty:
        n_files = len(table)
        n_data = int((table["file_type"] == "data").sum())
        n_code = int((table["file_type"] == "code").sum())
        n_readme = int((table["file_type"] == "readme").sum())
        n_zip = int((table["file_type"] == "archive").sum())
    else:
        n_files = n_data = n_code = n_readme = n_zip = 0

    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "repo_n": [n_repo],
        "files_n": [n_files],
        "files_data": [n_data],
        "files_code": [n_code],
        "files_readme": [n_readme],
        "files_zip": [n_zip],
    })

    if n_repo == 0:
        tl = "na"
        report = ["No repositories were referenced in the text."]
        summary_text = "No repositories found."
    else:
        repo_df = pd.DataFrame(unique)
        repo_block = md_table(repo_df, ["repo_url", "repo_type"],
                              ["Repository", "Type"]) if not repo_df.empty else ""
        if n_zip:
            tl = "yellow"
            report = ["Some repositories contain archive files which should be "
                      "unpacked.", repo_block]
            summary_text = f"{n_repo} repositories referenced with {n_files} files."
        else:
            tl = "green"
            report = [repo_block]
            summary_text = f"{n_repo} repositories referenced with {n_files} files."
        if not table.empty:
            file_block = md_table(table, ["file_name", "file_type", "file_location"],
                                  ["File", "Type", "Location"])
            report.append(file_block)
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)

