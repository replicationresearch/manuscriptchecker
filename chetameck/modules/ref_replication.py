"""Warn for citations of original studies with a known replication in FLoRA.

For every cited original that appears in the FLoRA replication database, report
whether it was replicated or reproduced, the outcome, an outcome quote and a
link to the replication study.
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ._data import flora, flora_online
from ._refs import refs_with_doi, doi_set

OUTCOME_COLOR = {
    "successful": "g",
    "failed": "r",
    "mixed": "y",
    "statistically successful but flawed": "y",
    "uninformative": "y",
    "descriptive only": "y",
    "computionally successful, robust": "g",
    "computionally successful, robustness challenges": "y",
}


@register("ref_replication")
def ref_replication(paper, prev_outputs=None):
    bib = refs_with_doi(paper)
    if bib.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No references with DOIs found.",
                             report=["No references with DOIs found."], na_replace=0)
    db = flora()
    if db.empty:
        # fall back to the latest FLoRA CSV from OSF (the "FLoRA API")
        db = flora_online()
    if db is None or db.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="FLoRA database unavailable.",
                             report=["FLoRA database unavailable."], na_replace=0)

    db = db.rename(columns={"doi_o": "doi", "apa_ref_o": "original_ref",
                            "apa_ref_r": "replication_ref",
                            "doi_r": "replication_doi", "url_r": "replication_url",
                            "outcome": "replication_outcome",
                            "outcome_quote": "outcome_quote",
                            "type": "replication_type"})
    db = db[["doi", "original_ref", "replication_ref", "replication_doi",
             "replication_url", "replication_outcome", "outcome_quote",
             "replication_type"]]

    merged = bib.merge(db, on="doi", how="inner")
    if not merged.empty:
        # drop rows where the replication DOI is already cited in the paper
        cited = doi_set(paper)
        merged = merged[~merged["replication_doi"].isin(cited)]

    merged = _format(merged)

    n = len(merged)
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "replications": [n]})
    if n == 0:
        tl = "na"
        report = ["No cited originals with a known replication were found."]
        summary_text = "No replication warnings."
    else:
        tl = "info"
        plural = "s" if n != 1 else ""
        verb = "have" if n != 1 else "has"
        report = [f"{n} cited original{plural} {verb} a known replication or "
                  f"reproduction in FLoRA:",
                  md_table(merged,
                           ["original_doi", "replication_type", "outcome",
                            "outcome_quote", "link"],
                           ["Original DOI", "Replication", "Outcome",
                            "Outcome quote", "Link to study"])]
        summary_text = (f"{n} cited original{plural} {verb}"
                        f" a known replication.")
    return module_output(table=merged, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _format(df):
    if df.empty:
        return df
    df = df.copy()
    df["replication_type"] = df["replication_type"].astype(str).str.title()
    df["replication_outcome"] = df["replication_outcome"].astype(str)
    df["outcome_quote"] = df["outcome_quote"].astype(str).str.strip()
    df["outcome_quote"] = df["outcome_quote"].replace(
        {"nan": "", "None": ""}).str.strip()
    # Colour-code the outcome
    def color_outcome(v):
        c = OUTCOME_COLOR.get(v.lower())
        return f"{{{c}}}{v}{{/}}" if c else v
    df["outcome"] = df["replication_outcome"].map(color_outcome)
    # Link to the study: prefer the url, else resolve the DOI
    df["link"] = df.apply(
        lambda r: (r["replication_url"] if pd.notna(r["replication_url"])
                   and str(r["replication_url"]).strip()
                   else f"https://doi.org/{r['replication_doi']}"
                   if pd.notna(r["replication_doi"])
                   and str(r["replication_doi"]).strip()
                   else ""), axis=1)
    df["original_doi"] = df["doi"]
    df["original_ref"] = df["original_ref"].astype(str).map(
        lambda s: re.sub(r"\s*https?://\S+\s*$", "", s).strip())
    return df[["original_doi", "original_ref", "replication_ref",
               "replication_type", "replication_outcome", "outcome",
               "outcome_quote", "link"]]
