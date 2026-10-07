"""List all URLs in the main text."""

from .registry import register, module_output, count_by_paper
from ..text import extract_urls


@register("all_urls")
def all_urls(paper, prev_outputs=None):
    table = extract_urls(paper)
    n = len(table)
    summary = count_by_paper(table, "urls")
    tl = "info" if n else "na"
    summary_text = f"We found {n} URL{'s' if n != 1 else ''} in the main text."
    report = []
    if n:
        cols = [c for c in ("text", "section_id") if c in table.columns]
        report.append(_table_md(table[cols].drop_duplicates(), ["URL", "Section"]))
    else:
        report.append("No URLs were detected in the main text.")
    return module_output(table=table, summary_table=summary,
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
