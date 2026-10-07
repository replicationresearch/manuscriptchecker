"""Flag citations to frequently-miscited papers using the bundled miscite database.

This is an *offline* check: it looks up each cited DOI against a locally
bundled database of papers with well-known miscitation patterns (results that
are frequently misreported or overgeneralised by citing papers). It needs no
network access - it was previously registered but never wired into any of the
default/fast module lists, so it silently never ran; it now does.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ._data import miscite
from ._refs import refs_with_doi


@register("ref_miscitation")
def ref_miscitation(paper, prev_outputs=None):
    bib = refs_with_doi(paper)
    db = miscite()
    if bib.empty or db.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No miscitation data.",
            report=["No miscitation database is bundled with this installation, "
                    "or the manuscript has no DOI'd references to check."],
            na_replace=0)

    merged = bib.merge(db, on="doi", how="inner", suffixes=("", "_miscite"))
    n = len(merged)
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "miscite_n": [n]})
    tl = "yellow" if n else "green"

    # Only the columns relevant to the report ever go into the table; the
    # previous version passed the full (many-column) merged frame to a
    # 2-header markdown table, which produced a mismatched/garbled table.
    display_cols = [c for c in ("doi", "reftext", "warning") if c in merged.columns]
    display_headers = {"doi": "DOI", "reftext": "Known miscitation",
                       "warning": "Warning"}
    headers = [display_headers[c] for c in display_cols]

    if n:
        report = [f"{n} citation{'s' if n != 1 else ''} to a frequently "
                  "miscited paper:",
                  md_table(merged, display_cols, headers)]
        summary_text = f"{n} miscitation warning{'s' if n != 1 else ''}."
    else:
        report = ["No citations to known frequently-miscited papers were found."]
        summary_text = "No miscitation warnings."
    return module_output(table=merged, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
