"""Flag p-values reported imprecisely (p < .05) or as exactly zero."""

import re

import pandas as pd

from .registry import register, module_output, count_by_paper
from ..text import extract_p_values, text_expand

STAR_PATTERN = re.compile(r"\*\s*p\s*<\s*0?\.0+[15]")


@register("stat_p_exact")
def stat_p_exact(paper, prev_outputs=None):
    p = extract_p_values(paper)
    if p.empty:
        return module_output(table=p,
                             summary_table=count_by_paper(p, "n_imprecise"),
                             traffic_light="na",
                             summary_text="We detected no *p* values.",
                             report=["We detected no *p* values."], na_replace=0)

    p = text_expand(p, paper, expand_to="sentence")
    p = p.copy()
    p["imprecise"] = ((p["p_comp"] == "<") & (p["p_value"] > 0.001)) | \
                     (~p["p_comp"].isin(["=", "<"])) | \
                     (p["p_value"].isna())
    stars = p["expanded"].astype(str).map(
        lambda s: bool(STAR_PATTERN.search(s)))
    p["imprecise"] = p["imprecise"] & ~stars
    p["zero"] = (p["p_comp"] == "=") & p["p_value"].notna() & (p["p_value"] == 0)

    imp = p[p["imprecise"]]
    zero = p[p["zero"]]
    n_total = len(p)

    # summary
    imp_sum = count_by_paper(imp, "n_imprecise")
    zero_sum = count_by_paper(zero, "n_zero")
    if imp_sum.empty and zero_sum.empty:
        summary = pd.DataFrame({"paper_id": [paper.paper_id]})
    elif imp_sum.empty:
        summary = zero_sum
    elif zero_sum.empty:
        summary = imp_sum
    else:
        summary = imp_sum.merge(zero_sum, on="paper_id", how="outer")

    if len(imp) == 0 and len(zero) == 0:
        tl = "green"
        report = [f"We found no imprecise *p* values or *p*-values of "
                  f"exactly zero out of {n_total} detected."]
        summary_text = report[0]
    else:
        tl = "red"
        parts = []
        if len(imp):
            parts.append(f"{len(imp)} imprecise *p* value"
                         f"{'s' if len(imp) != 1 else ''}")
        if len(zero):
            parts.append(f"{len(zero)} *p* value{'s' if len(zero) != 1 else ''} "
                         f"reported as exactly zero")
        summary_text = (f"We found {', '.join(parts)} out of {n_total} "
                        f"detected *p* value{'s' if n_total != 1 else ''}.")
        report = [summary_text]
        if len(imp):
            report.append(_table_md(imp[["text", "expanded"]],
                                    ["P-Value", "Text"]))
        if len(zero):
            report.append(_table_md(zero[["text", "expanded"]],
                                    ["P-Value", "Text"]))
    return module_output(table=p, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in df.columns) + " |")
    return "\n".join(lines)

