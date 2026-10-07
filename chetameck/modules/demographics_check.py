"""Check whether basic sample demographics are reported.

Looks for three common demographic reporting categories - age, gender/sex
composition, and sample origin (country/nationality/recruitment location) -
and flags whether each is present. Missing demographics make it harder for
readers to judge generalizability (e.g. WEIRD-sample concerns), a frequent
point in social-science review.
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

CATEGORIES = {
    "age": r"\b(?:mean age|age range|M\s*age|age\s*=\s*\d|aged? \d{1,3}"
          r"(?:\s*(?:to|-)\s*\d{1,3})?\s*years?)",
    "gender/sex": r"\b(?:\d{1,3}(?:\.\d+)?\s*%\s*(?:female|male|women|men)|"
                 r"\b\d+\s*(?:female|male|women|men)\b|gender identit|"
                 r"\bsex\s*:\s*\d)",
    "sample origin": r"\b(?:recruited (?:in|from)|nationalit|country of "
                     r"residence|sample (?:was|were) recruited|participants "
                     r"(?:were|was) from)",
}


@register("demographics_check")
def demographics_check(paper, prev_outputs=None):
    rows = []
    found_any = False
    for label, pattern in CATEGORIES.items():
        hits = text_search(paper, pattern)
        found = not hits.empty
        found_any = found_any or found
        rows.append({
            "category": label,
            "reported": "{g}yes{/}" if found else "{r}no{/}",
            "example": (str(hits["text"].iloc[0])[:150] if found else "-"),
        })

    table = pd.DataFrame(rows)
    n_missing = sum(1 for r in rows if r["reported"] == "{r}no{/}")
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "demographics_reported": [3 - n_missing],
                            "demographics_missing": [n_missing]})

    if n_missing == 0:
        tl = "green"
    elif n_missing == 3:
        tl = "red"
    else:
        tl = "yellow"

    report = [
        "Sample demographics reported in the manuscript:",
        md_table(table, ["category", "reported", "example"],
                 ["Category", "Reported?", "Example"]),
    ]
    if n_missing:
        report.append(f"**{n_missing} of 3** basic demographic categories were "
                      "not found - consider reporting them for readers to "
                      "judge generalizability.")
    summary_text = (f"{3 - n_missing}/3 demographic categories reported."
                    if found_any else "No sample demographics found.")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
