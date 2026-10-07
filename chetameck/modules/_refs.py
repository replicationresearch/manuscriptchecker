"""Reference helpers shared by the ref_* modules."""

import pandas as pd


def ref_table(paper):
    """Join bib + text to produce one row per reference with its text."""
    bib = paper.table("bib")
    text = paper.table("text")
    if bib.empty or text.empty:
        return pd.DataFrame(columns=["paper_id", "bib_id", "doi", "text"])
    cols = [c for c in ("paper_id", "bib_id", "doi", "text_id")
            if c in bib.columns]
    b = bib[cols].copy()
    b["paper_id"] = paper.paper_id
    merged = b.merge(text[["text_id", "text"]], on="text_id", how="left")
    merged["text"] = merged["text"]
    return merged[["paper_id", "bib_id", "doi", "text"]]


def refs_with_doi(paper):
    rt = ref_table(paper)
    if rt.empty or "doi" not in rt.columns:
        return pd.DataFrame(columns=["paper_id", "bib_id", "doi", "text"])
    rt = rt[rt["doi"].notna() & (rt["doi"].astype(str).str.strip() != "")]
    rt["doi"] = rt["doi"].astype(str).str.strip().str.lower()
    return rt.reset_index(drop=True)


def doi_set(paper):
    """The set of DOIs already cited in the paper (lowercased)."""
    rt = refs_with_doi(paper)
    if rt.empty:
        return set()
    return set(rt["doi"])
