"""Report whether the data are actually available (openly, or on request)."""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

ON_REQUEST = r"(on|upon)\s+(reasonable\s+)?request"
AVAILABILITY = (r"\bavailab|\bsupplement|\barchive|\baccess|\bshare|\bonline\b"
                r"|\bfound\b|\bfind\b|\bdetailed\b|\bsee\b")
REPO_WORDS = (r"http|repositor|archive|\bosf\b|open science framework|researchbox"
              r"|zenodo|github|figshare|datadryad|kaggle|mendeley|dataverse"
              r"|clinicalstudydatarequest|ourworldindata")
DATA_WORDS = r"\bdata\b|\bdataset"


@register("open_practices")
def open_practices(paper, prev_outputs=None):
    data = text_search(paper, DATA_WORDS)
    on_request = text_search(paper, ON_REQUEST)
    availability = text_search(paper, AVAILABILITY)
    repo = text_search(paper, REPO_WORDS)

    # Data sentences that also say something about where/how the data can be
    # obtained (a repository/URL, "available", or "on request").
    def has_any(rows, pattern):
        if rows.empty:
            return pd.Series(False, index=rows.index)
        return rows["text"].astype(str).map(
            lambda s: bool(re.search(pattern, s, re.I)))

    if data.empty:
        stmt = pd.DataFrame(columns=["text", "section_type", "header"])
    else:
        avail_mask = has_any(data, AVAILABILITY) | has_any(data, REPO_WORDS)
        req_mask = has_any(data, ON_REQUEST)
        keep = avail_mask | req_mask
        stmt = data[keep].copy()
        stmt["availability"] = [
            "on request" if req else "open"
            for req in req_mask[keep]
        ]
        cols = [c for c in ("text", "section_type", "header", "availability")
                if c in stmt.columns]
        stmt = stmt[cols].reset_index(drop=True)

    n_stmts = len(stmt)
    if n_stmts:
        open_stmts = (stmt["availability"] == "open").sum() if "availability" in stmt else 0
        on_req = (stmt["availability"] == "on request").sum() if "availability" in stmt else 0
    else:
        open_stmts = on_req = 0

    if n_stmts and open_stmts:
        tl = "green"
        verdict = "**Data availability:** Yes - the data are openly available."
        summary_text = "Data are openly available."
    elif n_stmts and on_req:
        tl = "yellow"
        verdict = "**Data availability:** On request only."
        summary_text = "Data are available on request only."
    else:
        tl = "red"
        verdict = ("**Data availability:** No data availability statement was "
                   "found.")
        summary_text = "No data availability statement found."

    report = [verdict]
    if n_stmts:
        report.append("Statements about data availability:")
        report.append(md_table(stmt, ["text", "availability", "section_type"],
                               ["Statement", "Availability", "Source section"]))
    else:
        report.append("No sentence describes where the data can be obtained.")

    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "data_open": [bool(open_stmts)],
        "on_request": [bool(on_req)],
        "data_statements": [stmt["text"].tolist() if n_stmts else []],
    })
    return module_output(table=stmt, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report,
                         na_replace={"data_open": False, "on_request": False})
