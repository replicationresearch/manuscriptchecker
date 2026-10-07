"""Flag sentences describing effects as 'marginally significant'."""

from .registry import register, module_output, count_by_paper, md_table
from ..text import text_search

PATTERN = (r"margin\w* (?:\w+\s+){0,5}significan\w*"
           r"|trend\w* (?:\w+\s+){0,1}significan\w*"
           r"|almost (?:\w+\s+){0,2}significan\w*"
           r"|approach\w* (?:\w+\s+){0,2}significan\w*"
           r"|border\w* (?:\w+\s+){0,2}significan\w*"
           r"|close to (?:\w+\s+){0,2}significan\w*")


@register("marginal")
def marginal(paper, prev_outputs=None):
    table = text_search(paper, PATTERN)
    n = len(table)
    summary = count_by_paper(table, "marginal")
    tl = "red" if n else "green"
    summary_text = (f"You described {n} effect{'s' if n != 1 else ''} "
                    f"with terms related to 'marginally significant'.")
    if tl == "green":
        report = ["No effects were described with terms related to "
                  "'marginally significant'."]
    else:
        report = [
            "You described effects with terms related to 'marginally "
            "significant'. If *p* values above 0.05 are interpreted as an "
            "effect, you inflate the alpha level and increase the Type 1 "
            "error rate.",
            md_table(table, ["text", "section_type"], ["Text", "Section"]),
        ]
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
