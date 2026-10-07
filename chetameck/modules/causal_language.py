"""Flag causal language used with a design that doesn't support causal claims.

Common criticism of social-science manuscripts: sentences like "X led to an
increase in Y" or "the intervention improved Y" imply causation, but the
Method section describes a correlational/cross-sectional design rather than
an experiment. This searches the whole text for causal phrasing and the
Method section for experimental-design markers (random assignment,
manipulation, a control/comparison condition), and flags causal sentences
found when no such marker is present.

Purely textual - a "correlational design + causal language" combination is
worth a look, not proof of an overclaim (e.g. instrumental-variable or
longitudinal designs can support causal language too, and this doesn't
recognise those).
"""

import pandas as pd

from .registry import register, module_output, md_table
from ..text import text_search

CAUSAL_PATTERN = (
    r"\b(?:caused?|causes|causing|led to|leads to|leading to|"
    r"result(?:ed|s)? in|impact(?:ed|s)? on|effect of .{1,40} on|"
    r"increases?|decreases?|improv(?:ed|es|ing)|reduc(?:ed|es|ing))\b"
)
EXPERIMENTAL_PATTERN = (
    r"\brandomly assigned|random assignment|randomi[sz]ed (?:controlled )?"
    r"trial|\bRCT\b|were manipulated|experimental (?:condition|group|"
    r"manipulation)|control(?:led)? condition|between-subjects design|"
    r"within-subjects design|quasi-experimental|instrumental variable"
)


@register("causal_language_check")
def causal_language_check(paper, prev_outputs=None):
    causal = text_search(paper, CAUSAL_PATTERN)
    if causal.empty:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No causal language detected.",
            report=["No causal language ('led to', 'increases', 'effect of X "
                    "on Y', ...) was found."], na_replace=0)

    design = text_search(paper, EXPERIMENTAL_PATTERN)
    has_design_marker = not design.empty

    table = causal[["text", "section_type"]].copy() if "section_type" in causal.columns \
        else causal[["text"]].copy()
    n = len(table)
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "causal_n": [n],
                            "design_marker_found": [has_design_marker]})

    if has_design_marker:
        tl = "green"
        report = [f"{n} causal statement{'s' if n != 1 else ''} found, and the "
                  "text also mentions an experimental/random-assignment "
                  "design marker, so causal language is plausibly justified."]
        summary_text = f"{n} causal statement(s); an experimental design marker was found."
    else:
        tl = "yellow"
        report = [
            f"{n} causal statement{'s' if n != 1 else ''} found, but no "
            "experimental-design marker (random assignment, manipulation, "
            "RCT, control condition, ...) was found anywhere in the text. "
            "If the design is correlational/cross-sectional, consider "
            "softening this language (e.g. 'was associated with' instead of "
            "'led to'):",
            md_table(table, list(table.columns), ["Statement", "Section"][:len(table.columns)]),
        ]
        summary_text = f"{n} causal statement(s) with no experimental-design marker found."
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
