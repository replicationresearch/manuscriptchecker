"""Module registry and shared helpers for ChetaMeck modules."""

import re

import pandas as pd

registry = {}


def register(name):
    """Decorator to register a module function under ``name``."""
    def deco(fn):
        registry[name] = fn
        return fn
    return deco


def module_output(table=None, summary_table=None, traffic_light="info",
                  summary_text="", report=None, na_replace=None):
    return {
        "table": table if table is not None else pd.DataFrame(),
        "summary_table": summary_table,
        "traffic_light": traffic_light,
        "summary_text": summary_text,
        "report": report or [],
        "na_replace": na_replace,
    }


def default_summary(paper):
    return pd.DataFrame({"paper_id": [paper.paper_id]})


def count_by_paper(df, colname):
    """Count rows per paper_id -> summary_table with a named count column."""
    if df is None or df.empty:
        return pd.DataFrame({"paper_id": [], colname: []})
    if "paper_id" not in df.columns:
        df = df.copy()
        df["paper_id"] = "unknown"
    return df.groupby("paper_id", dropna=False).size().reset_index(
        name=colname)


def plural(n, singular="", plural_s="s"):
    return singular if n == 1 else plural_s


def md_table(df, columns, headers=None):
    """Build a markdown table from a DataFrame using explicit column selection.

    ``columns`` are the DataFrame column names to render; ``headers`` (optional)
    are the human-readable column headings. Cells containing ``{g}``/``{r}``/
    ``{y}`` colour markers are passed through so the report renderer can colour
    them green/red/yellow.
    """
    if df is None or df.empty:
        return "_(no results)_"
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return "_(no results)_"
    headers = headers or cols
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r.get(c)
            cells.append("" if v is None or (isinstance(v, float) and pd.isna(v))
                         else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
