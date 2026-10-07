"""Summarize the results of previously-run reference modules."""

import pandas as pd

from .registry import register, module_output
from ._refs import ref_table


@register("ref_summary")
def ref_summary(paper, prev_outputs=None):
    table = ref_table(paper)
    if table.empty:
        return module_output(table=table,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No references found.",
                             report=["No references found."], na_replace=0)

    prev = prev_outputs or {}
    table = table.copy()
    for mod, col in (("ref_accuracy", "accuracy_mismatch"),
                     ("ref_retraction", "retractionwatch"),
                     ("ref_replication", "replication_type"),
                     ("ref_pubpeer", "pubpeer_comments")):
        out = prev.get(mod, {})
        t = out.get("table") if isinstance(out, dict) else None
        if t is not None and not t.empty:
            join_cols = [c for c in ("bib_id", "doi") if c in t.columns and c in table.columns]
            if join_cols:
                suffix_cols = [c for c in t.columns
                               if c not in join_cols and c not in table.columns]
                if suffix_cols:
                    table = table.merge(t[join_cols + suffix_cols],
                                        on=join_cols, how="left")

    n = len(table)
    report = [f"{n} reference{'s' if n != 1 else ''} found. See the individual "
              "reference modules for details."]
    return module_output(table=table,
                         summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                         traffic_light="info",
                         summary_text=f"{n} references found.",
                         report=report, na_replace=0)

