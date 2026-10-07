"""Recompute p-values for t- and F-tests to find reporting errors.

This is a Python port of the core statcheck logic: it finds APA-style
``t(df) = value, p = value`` and ``F(df1, df2) = value, p = value`` statements
and recomputes the p-value from the test statistic, comparing it to the
reported p-value. Only t- and F-tests are checked (the validated subset).
"""

import re

import pandas as pd
from scipy import stats

from .registry import register, module_output, md_table
from ..text import text_search

# Match t-tests / F-tests with a following p-value.
TEST_PATTERN = re.compile(
    r"(?:^|\s)([tT]\s*\(?\s*(\d+)\s*\)?\s*=\s*(-?\d+\.?\d*))"
    r"|(?:^|\s)([Ff]\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*(-?\d+\.?\d*))",
)
P_PATTERN = re.compile(r"p\s*([<>=~])\s*(\.?\d+)")


def _extract_tests(sentence):
    """Return a list of test dicts found in a sentence."""
    tests = []
    for m in TEST_PATTERN.finditer(sentence):
        if m.group(1):
            test = {
                "test_type": "t",
                "df": int(m.group(2)),
                "stat": float(m.group(3)),
                "raw": m.group(1).strip(),
            }
        elif m.group(4):
            test = {
                "test_type": "F",
                "df1": int(m.group(5)),
                "df2": int(m.group(6)),
                "stat": float(m.group(7)),
                "raw": m.group(4).strip(),
            }
        else:
            continue
        tests.append(test)
    return tests


def _compute_p(test):
    if test["test_type"] == "t":
        df = test["df"]
        stat = abs(test["stat"])
        if df <= 0:
            return None
        try:
            p = 2 * stats.t.sf(stat, df)
        except Exception:  # noqa: BLE001
            return None
    else:
        df1 = test["df1"]
        df2 = test["df2"]
        stat = abs(test["stat"])
        if df1 <= 0 or df2 <= 0:
            return None
        try:
            p = stats.f.sf(stat, df1, df2)
        except Exception:  # noqa: BLE001
            return None
    return p


@register("stat_check")
def stat_check(paper, prev_outputs=None):
    sentences = text_search(paper, "[0-9]")
    rows = []
    if not sentences.empty:
        for _, r in sentences.iterrows():
            sentence = str(r["text"])
            tests = _extract_tests(sentence)
            pm = P_PATTERN.search(sentence)
            reported_p = float(pm.group(2)) if pm else None
            for t in tests:
                t["paper_id"] = paper.paper_id
                t["reported_p"] = reported_p
                t["reported_p_comp"] = pm.group(1) if pm else None
                t["computed_p"] = _compute_p(t)
                t["text"] = sentence
                t["error"] = False
                t["decision_error"] = False
                if t["computed_p"] is not None and reported_p is not None:
                    if t["reported_p_comp"] == "<":
                        # an inequality is only an error if the computed p is
                        # NOT below the stated threshold.
                        if t["computed_p"] >= reported_p:
                            t["error"] = True
                            t["decision_error"] = (
                                (reported_p < 0.05) != (t["computed_p"] < 0.05))
                    else:
                        # equality: recomputed p should match the reported p
                        # (statcheck tolerance of 0.001 on the reported value)
                        if round(t["computed_p"], 3) != round(reported_p, 3):
                            t["error"] = True
                            if (reported_p < 0.05) != (t["computed_p"] < 0.05):
                                t["decision_error"] = True
                rows.append(t)

    table = pd.DataFrame(rows)
    if table.empty:
        return module_output(table=table,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No detectable t- or F-tests.",
                             report=["No detectable t- or F-tests. StatCheck "
                                     "currently only detects statistics written "
                                     "in APA format."])

    n_errors = int(table["error"].sum())
    summary = table.groupby("paper_id", dropna=False).agg(
        statcheck_found=("test_type", "size"),
        statcheck_errors=("error", "sum"),
        statcheck_decision_errors=("decision_error", "sum"),
    ).reset_index()
    tl = "red" if n_errors else "green"
    detail = _statcheck_details(table)
    if tl == "green":
        report = ["We detected no errors in t-tests or F-tests.",
                  detail]
        summary_text = report[0]
    else:
        summary_text = (f"{n_errors} possible error{'s' if n_errors != 1 else ''} "
                        f"in t-tests or F-tests")
        report = [
            "We detected possible errors in test statistics. Note that the "
            "accuracy of statcheck has only been validated for *t*-tests and "
            "*F*-tests.",
            detail,
        ]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _statcheck_details(table):
    """Build an expandable details block listing every t/F test identified,
    the recomputed p-value and the reported p-value."""
    rows = []
    for _, r in table.iterrows():
        err = bool(r["error"])
        dec = bool(r.get("decision_error"))
        typ = r.get("test_type", "")
        if typ == "t":
            test = f"t({r.get('df')}) = {r.get('stat')}"
        elif typ == "F":
            test = f"F({r.get('df1')}, {r.get('df2')}) = {r.get('stat')}"
        else:
            test = str(r.get("raw", ""))
        computed = r.get("computed_p")
        reported = r.get("reported_p")
        # colour the computed/reported p red when they disagree
        cp = (f"{{r}}{computed:.4g}{{/}}" if err else f"{computed:.4g}")
        rp = (f"{{r}}{reported:.4g}{{/}}" if err else f"{reported:.4g}")
        dec_txt = "{{r}}✗{{/}}" if dec else ("{{y}}✗{{/}}" if err else "✓")
        rows.append({
            "test": test,
            "computed_p": cp,
            "reported_p": rp,
            "decision": dec_txt,
            "sentence": str(r.get("text", ""))[:90] + ("…" if len(str(r.get("text", ""))) > 90 else ""),
        })
    df = pd.DataFrame(rows)
    table_md = md_table(df, ["test", "computed_p", "reported_p", "decision",
                             "sentence"],
                        ["Test statistic", "Computed p", "Reported p",
                         "Decision error", "Sentence"])
    return (f":::details Show all {len(table)} t/F tests identified "
            f"(computed vs reported)\n{table_md}\n:::")
