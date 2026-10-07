"""Find sentences describing statistical power analyses and classify type."""

import re

import pandas as pd

from .registry import register, module_output, count_by_paper
from ..text import text_search

POWER_WORDS = (r"\bpower\b|\bpowered\b|effect size|sample[- ]size"
               r"|a[- ]?priori|a[- ]?posteriori|post[- ]?hoc|sensitivity"
               r"|statistical power|to detect|achieve|observed power"
               r"|\bpower\s*=")
YEAR = re.compile(r"\b(19|20)\d{2}\b")


@register("power")
def power(paper, prev_outputs=None):
    paragraphs = text_search(paper, r"\bpower(ed|s)?\b", return_type="paragraph")
    rows = []
    if not paragraphs.empty:
        for _, r in paragraphs.iterrows():
            text = str(r["text"])
            if not re.search(POWER_WORDS, text, re.I):
                continue
            nums = re.findall(r"\d+", text)
            nums = [n for n in nums if not YEAR.fullmatch(n)]
            if not nums:
                continue
            rows.append({"text": text, "power_type": _classify(text)})
    table = pd.DataFrame(rows)

    n = len(table)
    summary = count_by_paper(table, "power_n")
    if n == 0:
        tl = "na"
        report = ["No power analyses were detected."]
        summary_text = report[0]
    else:
        # Without an LLM we can only regex-classify; report as yellow.
        tl = "yellow"
        summary_text = (f"We detected {n} power analys"
                        f"{'is' if n == 1 else 'es'}. The completeness of the "
                        f"reporting could not be fully verified.")
        report = [summary_text, _table_md(table, ["Sentence", "Power Type"])]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _classify(text):
    if re.search(r"a[- ]?priori|\bapriori\b", text, re.I):
        return "apriori"
    if re.search(r"sensitivity", text, re.I):
        return "sensitivity"
    if re.search(r"compromise", text, re.I):
        return "compromise"
    if re.search(r"a[- ]?posteriori|post[- ]?hoc|retrospective|observed", text, re.I):
        return "posthoc"
    return "unknown"


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in df.columns) + " |")
    return "\n".join(lines)

