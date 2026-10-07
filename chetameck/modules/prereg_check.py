"""Find preregistration links (AsPredicted / OSF) in the paper.

Every OSF link is resolved through the OSF API so the report shows what it
actually is (a registration, a project, a file, a preprint, ...). Only actual
OSF registrations (and AsPredicted links) count as preregistrations.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ._online import (aspredicted_links, osf_links, osf_link_info,
                      OSF_TYPE_LABEL)


@register("prereg_check")
def prereg_check(paper, prev_outputs=None):
    ap = aspredicted_links(paper)
    osf = osf_links(paper)

    osf_rows = []
    for u in osf:
        info = osf_link_info(u)
        typ = info.get("osf_type", "")
        osf_rows.append({
            "link": u,
            "type": OSF_TYPE_LABEL.get(typ, typ.replace("_", " ").title()
                                       if typ else "Unknown"),
            "title": info.get("title", ""),
        })
    osf_df = pd.DataFrame(osf_rows) if osf_rows else pd.DataFrame(
        columns=["link", "type", "title"])

    ap_rows = [{"link": u} for u in ap]
    ap_df = pd.DataFrame(ap_rows) if ap_rows else pd.DataFrame(
        columns=["link"])

    n_reg = int((osf_df["type"] == "Registration").sum()) if not osf_df.empty else 0
    n_ap = len(ap)
    n = n_reg + n_ap

    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "preregistration": [n],
        "osf_links": [len(osf)],
        "osf_registrations": [n_reg],
        "aspredicted_links": [n_ap],
    })

    if n == 0 and not osf and not ap:
        tl = "na"
        report = ["No preregistration links (AsPredicted or OSF) were found."]
        summary_text = "No preregistration links found."
    else:
        tl = "info"
        report = []
        if not osf_df.empty:
            report.append("**OSF links** (checked via the OSF API):")
            report.append(md_table(osf_df, ["link", "type", "title"],
                                   ["OSF link", "What it is", "Title"]))
        if not ap_df.empty:
            report.append("**AsPredicted links**:")
            report.append(md_table(ap_df, ["link"], ["AsPredicted link"]))
        if osf and n_reg == 0:
            report.append("None of the OSF links point to a registration.")
        if n == 0:
            report.append("No preregistration was found.")
            if osf:
                summary_text = "No registration among the OSF links."
            else:
                summary_text = "No preregistration links found."
        elif n == 1:
            summary_text = "1 preregistration found."
        else:
            summary_text = f"{n} preregistrations found."
    return module_output(table=osf_df, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
