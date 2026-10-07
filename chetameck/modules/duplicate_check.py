"""Detect internally duplicated / recycled text (self-plagiarism, salami slicing).

This does **not** check against external sources or other papers - neither
GROBID nor ChetaMeck has a plagiarism corpus to compare against. It flags text
duplicated *within the same manuscript*: verbatim sentences repeated across
different paragraphs, and paragraphs that are near-identical (e.g. copy-pasted
methods text reused almost unchanged in the discussion) - the two most common
markers of recycled/salami-sliced reporting that are actually detectable from
the manuscript alone.
"""

import re
from itertools import combinations

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

MIN_SENTENCE_WORDS = 12
NEAR_DUP_SHINGLE_K = 5
NEAR_DUP_THRESHOLD = 0.65
# Comparing every paragraph pair is O(n^2); skip on very long documents rather
# than hang on an outlier.
MAX_PARAGRAPHS_FOR_PAIRWISE = 400

_WORD_RE = re.compile(r"[a-z0-9]+")


def _norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", str(s).lower())
    return re.sub(r"\s+", " ", s).strip()


def _shingles(text, k=NEAR_DUP_SHINGLE_K):
    words = _WORD_RE.findall(text.lower())
    if len(words) < k:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def _jaccard(a, b):
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


@register("duplicate_check")
def duplicate_check(paper, prev_outputs=None):
    text = text_search(paper, ".*")
    if text.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No text to check.",
            report=["No text was extracted from this manuscript."], na_replace=0)

    text = text.copy()
    text["norm"] = text["text"].map(_norm)

    # --- 1. verbatim sentences repeated across different paragraphs --------
    exact_rows = []
    long_sents = text[text["norm"].str.split().str.len() >= MIN_SENTENCE_WORDS]
    if not long_sents.empty and "paragraph_id" in long_sents.columns:
        for norm_text, grp in long_sents.groupby("norm"):
            if grp["paragraph_id"].nunique() < 2:
                continue
            secs = sorted({str(s) for s in grp.get("section_type", [])
                          if s and str(s) != "nan"})
            exact_rows.append({
                "kind": "verbatim sentence",
                "text": grp["text"].iloc[0][:200],
                "occurrences": len(grp),
                "sections": ", ".join(secs) or "-",
            })

    # --- 2. near-duplicate paragraphs (5-gram shingle Jaccard) -------------
    near_rows = []
    if "paragraph_id" in text.columns:
        paras = (text.groupby("paragraph_id")
                    .agg(text=("text", lambda s: " ".join(s.astype(str))),
                         section_type=("section_type", "first"))
                    .reset_index())
        paras = paras[paras["text"].str.split().str.len() >= MIN_SENTENCE_WORDS]
        if 0 < len(paras) <= MAX_PARAGRAPHS_FOR_PAIRWISE:
            shingles = {pid: _shingles(t) for pid, t in
                       zip(paras["paragraph_id"], paras["text"])}
            by_pid = paras.set_index("paragraph_id")
            for (pid1, s1), (pid2, s2) in combinations(shingles.items(), 2):
                sim = _jaccard(s1, s2)
                if sim < NEAR_DUP_THRESHOLD:
                    continue
                row1, row2 = by_pid.loc[pid1], by_pid.loc[pid2]
                near_rows.append({
                    "kind": "near-duplicate paragraph",
                    "text": str(row1["text"])[:150] + " (...)",
                    "occurrences": 2,
                    "sections": (f"{row1.get('section_type') or '?'} / "
                                f"{row2.get('section_type') or '?'} "
                                f"(similarity {sim:.0%})"),
                })

    rows = exact_rows + near_rows
    table = pd.DataFrame(rows)
    n = len(table)
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "duplicate_n": [n]})
    tl = "yellow" if n else "green"
    if n:
        report = [
            f"{n} instance{'s' if n != 1 else ''} of duplicated or near-duplicated "
            "text found within the manuscript (not checked against external "
            "sources or other papers):",
            md_table(table, ["kind", "text", "occurrences", "sections"],
                     ["Type", "Text (truncated)", "Occurrences", "Where"]),
        ]
        summary_text = f"{n} duplicated/near-duplicated passage{'s' if n != 1 else ''} found."
    else:
        report = ["No internally duplicated or near-duplicated passages were "
                  "detected. Note: this only checks the manuscript against "
                  "itself, not against external sources or other papers."]
        summary_text = "No internal text duplication detected."
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
