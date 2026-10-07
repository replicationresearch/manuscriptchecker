"""Warn for citations found in the RetractionWatch database."""

import pandas as pd

from .registry import register, module_output
from ._data import retractionwatch
from ._refs import refs_with_doi


@register("ref_retraction")
def ref_retraction(paper, prev_outputs=None):
    bib = refs_with_doi(paper)
    if bib.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No references with DOIs found.",
                             report=["No references with DOIs found."], na_replace=0)
    rw = retractionwatch()
    if rw.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="RetractionWatch database unavailable.",
                             report=["RetractionWatch database unavailable."], na_replace=0)
    merged = bib.merge(rw, on="doi", how="inner")
    n = len(merged)
    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "retractionwatch": [n],
    })
    if n == 0:
        tl = "na"
        report = ["No cited references were found in the RetractionWatch "
                  "database."]
        summary_text = "No retracted references found."
    else:
        tl = "info"
        report = [f"{n} reference{'s' if n != 1 else ''} found in the "
                  "RetractionWatch database. Verify these citations.",
                  _table_md(merged, ["DOI", "RetractionWatch"])]
        summary_text = f"{n} retraction watch hit{'s' if n != 1 else ''}."
    return module_output(table=merged, summary_table=summary,
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

