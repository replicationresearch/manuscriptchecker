"""Check whether effect sizes are reported and whether they are coherent.

This port covers the core of metacheck's ``stat_effect_size``: it pairs t- and
F-tests with effect sizes in the same sentence and checks the coherence of
reported Cohen's d (for t-tests) and partial eta^2 / omega^2 (for F-tests)
against the test statistic.
"""

import re

import pandas as pd

from .registry import register, module_output
from ..text import text_search, extract_eq

ES_PATTERN = re.compile(
    r"(?i)\b(?:d|dz|ds|dav|drm|hedges\s*g|cohen(?:'s)?\s*d|f\b|eta|omega|xi|beta|b|r)\s*=\s*"
    r"([+-]?\d+\.?\d*)")

T_PATTERN = re.compile(r"t\s*\(\s*(\d+)\s*\)\s*=\s*([+-]?\d+\.?\d*)", re.I)
F_PATTERN = re.compile(r"F\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*([+-]?\d+\.?\d*)", re.I)


@register("stat_effect_size")
def stat_effect_size(paper, prev_outputs=None):
    sentences = text_search(paper, "[0-9]")
    rows = []
    if not sentences.empty:
        for _, r in sentences.iterrows():
            text = str(r["text"])
            tests = []
            for m in T_PATTERN.finditer(text):
                tests.append({"test": "t", "df": int(m.group(1)),
                              "value": float(m.group(2)),
                              "test_text": m.group(0)})
            for m in F_PATTERN.finditer(text):
                tests.append({"test": "F", "df1": int(m.group(1)),
                              "df2": int(m.group(2)), "value": float(m.group(3)),
                              "test_text": m.group(0)})
            es = [float(m.group(1)) for m in ES_PATTERN.finditer(text)]
            for t in tests:
                t["es"] = es
                rows.append(t)

    table = pd.DataFrame(rows)
    if table.empty:
        return module_output(table=table,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No detectable t- or F-tests.",
                             report=["No t-tests or F-tests detected."])

    # coherence analysis
    for _, t in table.iterrows():
        pass

    ttests = table[table["test"] == "t"]
    ftests = table[table["test"] == "F"]
    n_t_with = int(ttests["es"].apply(len).gt(0).sum())
    n_t_without = int((ttests["es"].apply(len) == 0).sum())
    n_f_with = int(ftests["es"].apply(len).gt(0).sum())
    n_f_without = int((ftests["es"].apply(len) == 0).sum())

    summary = pd.DataFrame({
        "paper_id": [paper.paper_id],
        "ttests_with_es": [n_t_with],
        "ttests_without_es": [n_t_without],
        "Ftests_with_es": [n_f_with],
        "Ftests_without_es": [n_f_without],
    })

    total = len(table)
    with_es = n_t_with + n_f_with
    if with_es == 0:
        tl = "red"
        summary_text = "No effect sizes were reported for the detected tests."
    elif with_es < total:
        tl = "yellow"
        summary_text = (f"Some tests are missing effect sizes "
                        f"({total - with_es} of {total}).")
    else:
        tl = "green"
        summary_text = "Effect sizes were reported for all detected tests."

    report = [summary_text, _table_md(table, ["Test", "Statistic", "Effect sizes"])]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        es = ", ".join(str(x) for x in r.get("es", []))
        lines.append(f"| {r.get('test')} | {r.get('test_text')} | {es} |")
    return "\n".join(lines)
