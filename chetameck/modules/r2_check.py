"""R2 Initial Editorial Assessment (from the R2 Initial Editorial Assessment Form).

Source: Müller, M., Röseler, L., & Wallrich, L. (2026). Initial Editorial
Assessment Form (Replication Research). Zenodo. https://doi.org/10.5281/zenodo.18229852

This module runs the automatable items from the R2 editorial checklist against
the paper and reports a status for each. It covers administrative completeness,
study registration & reproducibility, manuscript contents, and publication
transparency, where these can be assessed from the manuscript text and metadata.
"""

import re

import pandas as pd

from .registry import register, module_output
from ..text import text_search

# Patterns that indicate AI / generative-model use in the manuscript.
AI_PATTERN = (
    r"\b(?:ChatGPT|OpenAI|Claude|Gemini|Bard|Copilot|Qwen|Ollama|Mistral|"
    r"Llama|DeepSeek|Grok|Perplexity|Midjourney|DALL[- ]?E|Opus|Sonnet|Haiku|"
    r"GPT[- ]?[0-9]?|LLM|LLMs)\b"
    r"|large language model|generative AI|artificial intelligence|"
    r"AI[- ]?(?:tool|assistant|chatbot|generated|assisted|usage|model)"
)


def _yes_no(text, patterns):
    """Return True/False/None whether any pattern appears in the text."""
    if text is None or text == "":
        return None
    for pat in patterns:
        if re.search(pat, str(text), re.I):
            return True
    return False


def _search(paper, pattern):
    t = text_search(paper, pattern)
    return t["text"].tolist() if not t.empty else []


@register("r2_check")
def r2_check(paper, prev_outputs=None):
    items = []

    def add(item, found, notes=""):
        items.append({"item": item, "status": ("✅" if found else "❌"),
                      "found": bool(found), "notes": notes})

    # --- 1. Administrative completeness -----------------------------------
    ethics = _search(paper, r"ethic|IRB|institutional review|approval|consent")
    add("Ethical approval statement", bool(ethics),
        "; ".join(ethics[:2]) if ethics else "No ethics statement found.")

    cred = _search(paper, r"CRediT|author contribution|contribution statement")
    add("Author contributions (CRediT)", bool(cred),
        "CRediT statement found." if cred else "No CRediT statement found.")

    coi = _search(paper, r"conflict of interest|competing interest")
    add("Conflicts of interest", bool(coi),
        "COI statement found." if coi else "No COI statement found.")

    fund = _search(paper, r"funding|supported by|grant|funded")
    add("Funding transparency", bool(fund),
        "Funding statement found." if fund else "No funding statement found.")

    # --- 2. Study registration & reproducibility --------------------------
    prereg = _search(paper, r"pre-?regist|aspredicted|osf\.io")
    add("Study registration", bool(prereg),
        "Preregistration link/mention found." if prereg else
        "No preregistration found; may be stated as not preregistered.")

    protocol = _search(paper, r"protocol|preregistered analysis plan|pre-?analysis plan")
    add("Study protocol / analysis plan", bool(protocol),
        "Protocol/plan mention found." if protocol else "No protocol found.")

    materials = _search(paper, r"materials? (are|available|at)|osf\.io|zenodo|github")
    add("Materials transparency", bool(materials),
        "Materials link found." if materials else "No materials link found.")

    data = _search(paper, r"data (are|available|at)|data availability|dataset|osf\.io|zenodo")
    add("Data transparency", bool(data),
        "Data availability statement found." if data else "No data availability found.")

    code = _search(paper, r"code (is|are|available|at)|analytic code|replication package|github")
    add("Analytic code transparency", bool(code),
        "Code availability found." if code else "No code availability found.")

    # --- 3. Manuscript contents & technical checks -------------------------
    refs = paper.table("bib")
    ref_ok = bool(len(refs))
    add("References present", ref_ok,
        f"{len(refs)} references parsed." if ref_ok else "No references parsed.")

    doi = paper.info.iloc[0].get("doi") if not paper.info.empty else ""
    add("DOI present", bool(doi), f"DOI: {doi}" if doi else "No DOI found.")

    # --- 4. Supplementary materials & publication transparency -------------
    preprint = _search(paper, r"preprint|psyArXiv|arxiv|pre-print")
    add("Open access / preprint", bool(preprint),
        "Preprint mention found." if preprint else "No preprint mention found.")

    ai = _search(paper, AI_PATTERN)
    add("AI tool disclosure", bool(ai),
        ("AI use disclosed: " + "; ".join(ai[:2])) if ai else
        "No AI-use disclosure found.")

    sir = _search(paper, r"social impact")
    add("Social impact & responsibility section", bool(sir),
        "SIR section found." if sir else "No 'Social Impact' section found.")

    table = pd.DataFrame(items)
    n_ok = int(table["found"].sum()) if not table.empty else 0
    n = len(table)
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "r2_checks": [n], "r2_passed": [n_ok]})
    tl = "yellow" if n_ok < n else "green"
    report = [
        f"R2 Initial Editorial Assessment: {n_ok} of {n} automatable checks "
        f"passed.",
        "This is an automated approximation of the R2 initial editorial form. "
        "Items that require manual verification (link functionality, FAIR "
        "standards, ethics details, peer-review transparency) are not assessed "
        "here.",
        _table_md(table[["item", "status", "notes"]],
                  ["Check", "Status", "Notes"]),
    ]
    summary_text = f"{n_ok}/{n} R2 editorial checks passed."
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    cols = list(df.columns)
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
    return "\n".join(lines)
