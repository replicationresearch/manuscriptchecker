"""Identify non-significant p-values for manual review."""

from .registry import register, module_output
from ..text import extract_p_values, text_expand


@register("stat_p_nonsig")
def stat_p_nonsig(paper, prev_outputs=None):
    table = extract_p_values(paper)
    if not table.empty:
        cond = (table["p_value"].notna()) & \
               (table["p_value"] <= 0.05) & \
               (table["p_comp"].notna()) & \
               (table["p_comp"].isin(["<", "="]))
        table = table.copy()
        table["significance"] = ["significant" if c else "nonsignificant"
                                 for c in cond]
        table = table[table["significance"] == "nonsignificant"]
        table = text_expand(table, paper, expand_to="sentence")

    n = len(table)
    summary = table.groupby("paper_id", dropna=False).size().reset_index(
        name="n_nonsignificant") if n else None
    tl = "yellow" if n else "green"
    if tl == "green":
        report = ["We detected no nonsignificant p values."]
        summary_text = report[0]
    else:
        summary_text = (f"We found {n} non-significant p value"
                        f"{'s' if n != 1 else ''} that should be checked "
                        f"for appropriate interpretation.")
        report = [
            summary_text,
            "It is incorrect to infer that there is 'no effect' or 'no "
            "difference' after *p* > 0.05. The study may simply not have "
            "detected a true non-zero effect.",
            _table_md(table[["text", "expanded"]], ["Text", "Sentence"]),
        ]
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
