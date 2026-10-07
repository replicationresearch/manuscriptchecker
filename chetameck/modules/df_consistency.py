"""Cross-check reported degrees of freedom against the manuscript's own stated N.

A t-test's df implies a minimum sample size (independent-samples: df = n1+n2-2,
so N >= df+2), and a one-way F-test's df1/df2 implies N >= df1+df2+2. This
module extracts every reported test statistic's df (already parsed by
``extract_eq``) and the largest "N = ..." figure mentioned in the text, then
flags any test whose implied minimum sample size exceeds the manuscript's own
stated N - a strong signal of either a typo/reporting error or a real
inconsistency worth an editor's attention.

This is a heuristic, not a proof: multi-study papers, per-condition subsets
and post-hoc exclusions can all legitimately produce a smaller test-level n
than the headline N. Treat flags as "worth checking", not "wrong".
"""

import re

import pandas as pd

from .registry import register, module_output, md_table
from ..text import extract_eq, text_search

N_PATTERN = r"\b[Nn]\s*=\s*(\d{2,6})\b"

_T_RE = re.compile(r"\bt\s*$", re.I)
_F_RE = re.compile(r"\bF\s*$", re.I)
_CHI_RE = re.compile(r"(χ|chi)\s*2?\s*$", re.I)


def _reported_n(paper):
    """Largest N mentioned anywhere in the text (heuristic overall sample size)."""
    hits = text_search(paper, N_PATTERN, return_type="match", perl=True,
                       ignore_case=False)
    if hits.empty:
        return None
    vals = []
    for t in hits["text"]:
        m = re.search(N_PATTERN, str(t))
        if m:
            vals.append(int(m.group(1)))
    return max(vals) if vals else None


def _parse_df(df_str):
    """``'(118)'`` -> ``[118]``; ``'(2, 116)'`` -> ``[2, 116]``."""
    if df_str is None or (isinstance(df_str, float) and pd.isna(df_str)):
        return []
    if not df_str:
        return []
    inner = str(df_str).strip("() ")
    out = []
    for part in re.split(r"[,;]\s*", inner):
        part = part.strip()
        try:
            out.append(float(part))
        except ValueError:
            continue
    return out


def _implied_min_n(lhs, dfs):
    lhs = str(lhs or "")
    if _T_RE.search(lhs) and len(dfs) == 1:
        return dfs[0] + 2  # conservative: independent-samples t-test
    if _F_RE.search(lhs) and len(dfs) == 2:
        return dfs[0] + dfs[1] + 2
    return None  # chi-square df relates to categories, not n - not checkable this way


@register("df_consistency_check")
def df_consistency_check(paper, prev_outputs=None):
    eq = extract_eq(paper)
    if eq.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No test statistics with df found.",
            report=["No t/F test statistics with degrees of freedom were found."],
            na_replace=0)

    n_reported = _reported_n(paper)
    if n_reported is None:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="No overall sample size (N = ...) found to check against.",
            report=["Test statistics were found, but no overall sample size "
                    "('N = ...') was found in the text to check them against."],
            na_replace=0)

    rows = []
    for _, r in eq.iterrows():
        dfs = _parse_df(r.get("df"))
        if any(pd.isna(d) for d in dfs):
            continue
        min_n = _implied_min_n(r.get("lhs"), dfs)
        if min_n is None:
            continue
        ok = min_n <= n_reported
        rows.append({
            "statistic": (f"{r.get('lhs', '')}{r.get('df', '')} "
                         f"{r.get('comp', '')} {r.get('rhs', '')}").strip(),
            "implied_min_n": int(min_n),
            "reported_n": n_reported,
            "consistent": "{g}yes{/}" if ok else "{r}no{/}",
        })

    table = pd.DataFrame(rows)
    if table.empty:
        return module_output(
            table=table,
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id],
                                        "df_checked": [0], "df_inconsistent": [0]}),
            traffic_light="na",
            summary_text="No t/F tests with a checkable df were found.",
            report=["The test statistics found were not of a type (independent "
                    "t or one-way F) whose implied sample size could be checked."],
            na_replace=0)

    n_bad = int((table["consistent"] == "{r}no{/}").sum())
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "df_checked": [len(table)],
                            "df_inconsistent": [n_bad]})
    tl = "red" if n_bad else "green"
    report = [
        f"Manuscript's own largest stated sample size: N = {n_reported}. "
        f"{len(table)} test statistic{'s' if len(table) != 1 else ''} checked "
        "against it (df implies a minimum N):",
        md_table(table, ["statistic", "implied_min_n", "reported_n", "consistent"],
                 ["Statistic", "Implied min. N", "Reported N", "Consistent?"]),
    ]
    if n_bad:
        report.append(f"**{n_bad} test statistic{'s' if n_bad != 1 else ''}** imply "
                      "a larger sample than the manuscript's own stated N - check "
                      "for a df typo, an unflagged subsample, or a reporting error.")
    summary_text = (f"{n_bad} of {len(table)} test statistic(s) imply a sample size "
                    f"larger than the reported N = {n_reported}."
                    if n_bad else
                    f"All {len(table)} checkable test statistic(s) are consistent "
                    f"with the reported N = {n_reported}.")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
