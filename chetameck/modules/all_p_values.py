"""List all p-values in the text."""

from .registry import register, module_output, count_by_paper
from ..text import extract_p_values, text_expand


@register("all_p_values")
def all_p_values(paper, prev_outputs=None):
    p = extract_p_values(paper)
    n = len(p)
    summary = count_by_paper(p, "p_values")
    tl = "info" if n else "na"
    summary_text = f"We found {n} p-value{'s' if n != 1 else ''}"
    if n:
        p = text_expand(p, paper, expand_to="sentence")
        cols = [c for c in ("text", "expanded") if c in p.columns]
        rep = p[cols].drop_duplicates()
        report = [_table_md(rep, ["P-Value", "Sentence"])]
    else:
        report = ["We detected no *p* values."]
    return module_output(table=p, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    rows = []
    for _, r in df.iterrows():
        cells = [str(r.get(c, "")) for c in df.columns]
        rows.append("| " + " | ".join(cells) + " |")
    hdr = "| " + " | ".join(df.columns) + " |"
    sep = "| " + " | ".join(["---"] * len(df.columns)) + " |"
    return "\n".join([hdr, sep] + rows)
