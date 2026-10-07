"""Forensic metascience modules (from Heathers, 'An Introduction to Forensic Metascience').

These reimplement the quantitative, automatable techniques described in the book
as selectable ChetaMeck modules:

    grim_check       - GRIM: is a reported mean possible given n?
    grimmer_check    - GRIMMER: do mean/SD/n imply a whole-number sum of squares?
    sd_range_check   - Quick SD check: SD must not exceed the max for the range
    sd_se_check      - SD/SE confusion: SD = sqrt(n) * SE
    debit_check      - DEBIT: binary mean/SD consistency
    stalt_check      - STALT: p reported only as an inequality hiding an extreme p
    csf_check        - Carlisle-Stouffer-Fisher omnibus on a set of p-values
    test_recalc      - recalculate an independent-samples t-test from descriptives
"""

import math
import re

import pandas as pd
from scipy import stats

from .registry import register, module_output, count_by_paper
from ..descriptives import extract_descriptives, grim, grimmer, max_sd_for_range, debit
from ..text import text_search, extract_p_values


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GRIM
# ---------------------------------------------------------------------------
@register("grim_check")
def grim_check(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        for _, r in desc.iterrows():
            if pd.isna(r.get("mean")) or pd.isna(r.get("n")):
                continue
            n = int(r["n"])
            if n <= 0:
                continue
            ok, poss, reason = grim(r["mean"], n)
            rows.append({"text_id": r["text_id"], "mean": r["mean"], "n": n,
                         "grim": bool(ok), "possible_sum": poss,
                         "text": r["text"]})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["paper_id"] = paper.paper_id
    fails = table[table["grim"] == False] if not table.empty else table
    n_fail = len(fails)
    summary = count_by_paper(fails, "grim_fail") if n_fail else \
        pd.DataFrame({"paper_id": [paper.paper_id], "grim_fail": [0]})
    tl = "red" if n_fail else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No means with sample sizes were found to test with GRIM."]
        summary_text = report[0]
    elif n_fail:
        report = [f"GRIM: {n_fail} reported mean"
                  f"{'s' if n_fail != 1 else ''} ar"
                  f"{'e' if n_fail != 1 else 's'} impossible given the sample size.",
                  "For integer-valued data (counts, Likert scores), the sum "
                  "`mean x n` must be a whole number. The reported mean/n pair "
                  "is inconsistent with an integer-valued variable.",
                  _table_md(fails[["mean", "n", "text"]],
                            ["Mean", "n", "Sentence"])]
        summary_text = f"GRIM flagged {n_fail} mean{'s' if n_fail != 1 else ''}."
    else:
        report = ["GRIM: all reported means are consistent with their sample sizes."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# GRIMMER
# ---------------------------------------------------------------------------
@register("grimmer_check")
def grimmer_check(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        for _, r in desc.iterrows():
            if pd.isna(r.get("mean")) or pd.isna(r.get("sd")) or pd.isna(r.get("n")):
                continue
            n = int(r["n"])
            if n <= 1:
                continue
            ok, target, val, reason = grimmer(r["mean"], r["sd"], n)
            rows.append({"text_id": r["text_id"], "mean": r["mean"],
                         "sd": r["sd"], "n": n, "ok": bool(ok),
                         "sum_sq": val, "nearest": target,
                         "reason": reason, "text": r["text"]})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["paper_id"] = paper.paper_id
    fails = table[table["ok"] == False] if not table.empty else table
    n_fail = len(fails)
    summary = count_by_paper(fails, "grimmer_fail") if n_fail else \
        pd.DataFrame({"paper_id": [paper.paper_id], "grimmer_fail": [0]})
    tl = "red" if n_fail else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No mean/SD/n triples were found to test with GRIMMER."]
        summary_text = report[0]
    elif n_fail:
        report = [f"GRIMMER: {n_fail} mean/SD/n triple"
                  f"{'s' if n_fail != 1 else ''} do not imply a whole-number "
                  f"sum of squares.",
                  "For integer data, (n-1) x SD^2 + n x mean^2 must be a whole "
                  "number (the sum of squared values). A non-integer result is "
                  "inconsistent with an integer-valued variable.",
                  _table_md(fails[["mean", "sd", "n", "reason", "text"]],
                            ["Mean", "SD", "n", "Reason", "Sentence"])]
        summary_text = f"GRIMMER flagged {n_fail} mean/SD/n triple{'s' if n_fail != 1 else ''}."
    else:
        report = ["GRIMMER: all reported mean/SD/n triples imply a whole-number "
                  "sum of squares."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# Quick SD check
# ---------------------------------------------------------------------------
@register("sd_range_check")
def sd_range_check(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        for _, r in desc.iterrows():
            if pd.isna(r.get("sd")) or pd.isna(r.get("min")) or pd.isna(r.get("max")):
                continue
            n = int(r["n"]) if not pd.isna(r.get("n")) else None
            bound = max_sd_for_range(n, r["min"], r["max"]) if n else \
                (r["max"] - r["min"]) / 2
            if bound is None:
                continue
            ok = r["sd"] <= bound
            rows.append({"text_id": r["text_id"], "sd": r["sd"], "min": r["min"],
                         "max": r["max"], "max_sd": round(bound, 4),
                         "ok": bool(ok), "text": r["text"]})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["paper_id"] = paper.paper_id
    fails = table[table["ok"] == False] if not table.empty else table
    n_fail = len(fails)
    summary = count_by_paper(fails, "sd_issues") if n_fail else \
        pd.DataFrame({"paper_id": [paper.paper_id], "sd_issues": [0]})
    tl = "red" if n_fail else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No SDs with an accompanying range were found."]
        summary_text = report[0]
    elif n_fail:
        report = [f"Quick SD check: {n_fail} standard deviation"
                  f"{'s' if n_fail != 1 else ''} exceed"
                  f"{'s' if n_fail == 1 else ''} the maximum possible for the "
                  f"stated range.",
                  "The maximum possible SD for a sample is about half the range "
                  "(exactly sqrt(n/(n-1)) x (max-min)/2). An SD above this is "
                  "impossible.",
                  _table_md(fails[["sd", "min", "max", "max_sd", "text"]],
                            ["SD", "Min", "Max", "Max possible", "Sentence"])]
        summary_text = f"SD check flagged {n_fail} standard deviation{'s' if n_fail != 1 else ''}."
    else:
        report = ["Quick SD check: all SDs are within the maximum possible for "
                  "their ranges."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# SD/SE confusion
# ---------------------------------------------------------------------------
@register("sd_se_check")
def sd_se_check(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        for _, r in desc.iterrows():
            if pd.isna(r.get("sd")) or pd.isna(r.get("n")):
                continue
            n = int(r["n"])
            if n <= 1:
                continue
            # SD = sqrt(n) * SE  =>  the "SD" could be an SE
            implied_sd = math.sqrt(n) * r["sd"]
            # If the implied SD is implausibly large relative to a plausible
            # 0..range of the variable, flag. We use a heuristic: if converting
            # the reported SD as if it were an SE gives an SD that is more than
            # 10x the reported value, the author likely wrote SE but meant SD.
            rows.append({"text_id": r["text_id"], "reported": r["sd"],
                         "n": n, "if_se_then_sd": round(implied_sd, 3),
                         "ratio": round(implied_sd / r["sd"], 2),
                         "suspect": implied_sd > 10 * r["sd"],
                         "text": r["text"]})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["paper_id"] = paper.paper_id
    fails = table[table["suspect"] == True] if not table.empty else table
    n_fail = len(fails)
    summary = count_by_paper(fails, "sd_se_suspect") if n_fail else \
        pd.DataFrame({"paper_id": [paper.paper_id], "sd_se_suspect": [0]})
    tl = "yellow" if n_fail else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No SD/SE conversions could be tested (needs SD and n)."]
        summary_text = report[0]
    elif n_fail:
        report = [f"SD/SE check: {n_fail} reported variability"
                  f" measure{'s' if n_fail != 1 else ''} may be a standard error "
                  f"that was reported as a standard deviation.",
                  "If the value is an SE, the implied SD is sqrt(n) x SE. A "
                  "much larger implied SD suggests SD and SE were confused. "
                  "Verify the reported values.",
                  _table_md(fails[["reported", "n", "if_se_then_sd", "text"]],
                            ["Reported", "n", "Implied SD", "Sentence"])]
        summary_text = f"SD/SE check flagged {n_fail} possible confusion{'s' if n_fail != 1 else ''}."
    else:
        report = ["SD/SE check: no SD/SE confusion detected."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# DEBIT (binary data)
# ---------------------------------------------------------------------------
@register("debit_check")
def debit_check(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        for _, r in desc.iterrows():
            mean = r.get("mean")
            sd = r.get("sd")
            if pd.isna(mean) or pd.isna(sd):
                continue
            if mean < 0 or mean > 1:
                continue  # only binary/proportion means
            ok, expected, reason = debit(mean, sd)
            rows.append({"text_id": r["text_id"], "mean": mean, "sd": sd,
                         "expected_sd": round(expected, 3) if expected else None,
                         "ok": bool(ok), "reason": reason, "text": r["text"]})
    table = pd.DataFrame(rows)
    if not table.empty:
        table["paper_id"] = paper.paper_id
    fails = table[table["ok"] == False] if not table.empty else table
    n_fail = len(fails)
    summary = count_by_paper(fails, "debit_issues") if n_fail else \
        pd.DataFrame({"paper_id": [paper.paper_id], "debit_issues": [0]})
    tl = "red" if n_fail else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No binary/proportion means with SDs were found to test with "
                  "DEBIT."]
        summary_text = report[0]
    elif n_fail:
        report = [f"DEBIT: {n_fail} reported mean/SD pair"
                  f"{'s' if n_fail != 1 else ''} is inconsistent with binary "
                  f"(0/1) data.",
                  "For binary data the SD is fully determined by the mean: "
                  "SD = sqrt(p(1-p)), with a maximum of 0.5. An SD above 0.5, "
                  "or one that does not match the mean, is impossible.",
                  _table_md(fails[["mean", "sd", "expected_sd", "reason", "text"]],
                            ["Mean", "SD", "Expected SD", "Reason", "Sentence"])]
        summary_text = f"DEBIT flagged {n_fail} binary inconsistency{'s' if n_fail != 1 else ''}."
    else:
        report = ["DEBIT: all binary/proportion mean/SD pairs are consistent."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# STALT (p reported as inequality hiding an extreme p)
# ---------------------------------------------------------------------------
@register("stalt_check")
def stalt_check(paper, prev_outputs=None):
    # Find test statistics and recompute exact p-values.
    tpat = re.compile(r"t\s*\(\s*(\d+)\s*\)\s*=\s*(-?\d+\.?\d*)", re.I)
    fpat = re.compile(r"F\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*(-?\d+\.?\d*)", re.I)
    # p reported as an inequality like "p < .001"
    p_in = re.compile(r"p\s*<\s*(\.?\d+)", re.I)
    rows = []
    for _, r in text_search(paper, "p\\s*<").iterrows():
        text = str(r["text"])
        pm = p_in.search(text)
        if not pm:
            continue
        threshold = float(pm.group(1))
        computed = None
        raw = ""
        tm = tpat.search(text)
        if tm:
            computed = 2 * stats.t.sf(abs(float(tm.group(2))), int(tm.group(1)))
            raw = tm.group(0)
        else:
            fm = fpat.search(text)
            if fm:
                computed = stats.f.sf(abs(float(fm.group(3))),
                                      int(fm.group(1)), int(fm.group(2)))
                raw = fm.group(0)
        if computed is None:
            continue
        # STALT: the true p is far below the reported threshold
        stalt = computed < threshold * 0.1
        rows.append({"text_id": r["text_id"], "raw": raw,
                     "reported": f"p < {threshold}",
                     "computed_p": computed,
                     "stalt": bool(stalt), "text": text})
    table = pd.DataFrame(rows)
    stalt = table[table["stalt"] == True] if not table.empty else table
    n = len(stalt)
    summary = count_by_paper(stalt, "stalt_issues") if n else \
        pd.DataFrame({"paper_id": [paper.paper_id], "stalt_issues": [0]})
    tl = "yellow" if n else ("green" if not table.empty else "na")
    if table.empty:
        report = ["No p-values reported as inequalities with a recalculable test "
                  "statistic were found."]
        summary_text = report[0]
    elif n:
        report = [f"STALT: {n} p-value{'s' if n != 1 else ''} reported as an "
                  f"inequality ha{'s' if n == 1 else 've'} a much smaller true p.",
                  "Reporting 'p < x' can hide an extremely small true p-value. "
                  "Whether this is problematic depends on field conventions; "
                  "consider reporting the exact value.",
                  _table_md(stalt[["raw", "reported", "computed_p", "text"]],
                            ["Statistic", "Reported", "Computed p", "Sentence"])]
        summary_text = f"STALT flagged {n} under-reported p-value{'s' if n != 1 else ''}."
    else:
        report = ["STALT: no p-values reported as inequalities hide a much "
                  "smaller true p."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# CSF omnibus (Carlisle-Stouffer-Fisher)
# ---------------------------------------------------------------------------
@register("csf_check")
def csf_check(paper, prev_outputs=None):
    p = extract_p_values(paper)
    if p.empty or "p_value" not in p.columns:
        return module_output(table=p,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No p-values found to combine.",
                             report=["No p-values found to combine."], na_replace=0)
    vals = p["p_value"].dropna().tolist()
    if not vals:
        return module_output(table=p,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No numeric p-values found.",
                             report=["No numeric p-values found."], na_replace=0)

    def stouffer(ps):
        z = [stats.norm.ppf(1 - v) for v in ps]
        zc = sum(z) / math.sqrt(len(z))
        return 2 * (1 - stats.norm.cdf(abs(zc)))

    def fisher(ps):
        chi = -2 * sum(math.log(v) for v in ps)
        return stats.chi2.sf(chi, 2 * len(ps))

    combined_s = stouffer(vals)
    combined_f = fisher(vals)
    rows = [{"p": v} for v in vals]
    table = pd.DataFrame(rows)
    # A very small combined p on many baseline p-values is a red flag.
    suspicious = combined_s < 0.0001
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "n_pvalues": [len(vals)],
                            "stouffer_p": [combined_s],
                            "fisher_p": [combined_f]})
    tl = "yellow" if suspicious else "info"
    report = [
        f"Combined {len(vals)} p-value{'s' if len(vals) != 1 else ''} using the "
        f"Carlisle-Stouffer-Fisher omnibus test.",
        f"Stouffer's combined p = {combined_s:.6g}; Fisher's combined p = "
        f"{combined_f:.6g}.",
        ("A very small combined p suggests the p-values may be non-random or "
         "overly homogeneous. Interpret with care: Table 1 p-values are often "
         "mutually dependent." if suspicious else
         "The combined p-values are not unusually small."),
    ]
    summary_text = (f"CSF combined p = {combined_s:.4g}" +
                    (" (suspicious)" if suspicious else ""))
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


# ---------------------------------------------------------------------------
# test_recalc: independent-samples t-test from group descriptives
# ---------------------------------------------------------------------------
@register("test_recalc")
def test_recalc(paper, prev_outputs=None):
    desc = extract_descriptives(paper)
    rows = []
    if not desc.empty:
        groups = []
        for _, r in desc.iterrows():
            if pd.isna(r.get("mean")) or pd.isna(r.get("sd")) or pd.isna(r.get("n")):
                continue
            groups.append({"mean": r["mean"], "sd": r["sd"],
                           "n": int(r["n"]), "text_id": r["text_id"],
                           "text": r["text"]})
        # pair up groups sharing a text_id (two groups in the same sentence)
        from collections import defaultdict
        by_text = defaultdict(list)
        for g in groups:
            by_text[g["text_id"]].append(g)
        for tid, gs in by_text.items():
            if len(gs) < 2:
                continue
            g1, g2 = gs[0], gs[1]
            t = (g1["mean"] - g2["mean"]) / math.sqrt(
                g1["sd"] ** 2 / g1["n"] + g2["sd"] ** 2 / g2["n"])
            df = g1["n"] + g2["n"] - 2
            p = 2 * stats.t.sf(abs(t), df)
            rows.append({"text_id": tid,
                         "group1": f"M={g1['mean']}, SD={g1['sd']}, n={g1['n']}",
                         "group2": f"M={g2['mean']}, SD={g2['sd']}, n={g2['n']}",
                         "t": round(t, 3), "df": df, "p": p, "text": g1["text"]})
    table = pd.DataFrame(rows)
    n = len(table)
    summary = count_by_paper(table, "t_tests") if n else \
        pd.DataFrame({"paper_id": [paper.paper_id], "t_tests": [0]})
    tl = "info" if n else "na"
    if n:
        report = [f"Recalculated {n} independent-samples t-test"
                  f"{'s' if n != 1 else ''} from reported descriptive statistics.",
                  "These are computed assuming equal variance (Student's t). "
                  "Papers may have used Welch's t-test; verify if a recomputed "
                  "p differs from the reported one.",
                  _table_md(table[["group1", "group2", "t", "df", "p", "text"]],
                            ["Group 1", "Group 2", "t", "df", "p", "Sentence"])]
        summary_text = f"{n} t-test{'s' if n != 1 else ''} recalculated."
    else:
        report = ["No paired groups with means, SDs and sample sizes were found "
                  "to recalculate a t-test."]
        summary_text = report[0]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
