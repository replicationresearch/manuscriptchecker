"""Warn for citations that have comments on PubPeer (excluding Statcheck)."""

import requests

import pandas as pd

from .registry import register, module_output
from ._refs import refs_with_doi


@register("ref_pubpeer")
def ref_pubpeer(paper, prev_outputs=None):
    bib = refs_with_doi(paper)
    if bib.empty:
        return module_output(table=pd.DataFrame(),
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No references with DOIs found.",
                             report=["No references with DOIs found."], na_replace=0)

    rows = []
    for _, r in bib.iterrows():
        doi = r["doi"]
        info = _pubpeer(doi)
        if info:
            rows.append({"paper_id": paper.paper_id, "bib_id": r["bib_id"],
                         "doi": doi, "total_comments": info["total_comments"],
                         "url": info["url"], "users": info["users"],
                         "text": r.get("text", "")})
    table = pd.DataFrame(rows)
    n = len(table)
    total = int(table["total_comments"].sum()) if n else 0
    summary = pd.DataFrame({"paper_id": [paper.paper_id],
                            "pubpeer_comments": [total]})
    if n == 0:
        tl = "na"
        report = ["No citations with PubPeer comments were found."]
        summary_text = "No PubPeer comments found."
    else:
        tl = "info"
        report = [f"{n} cited reference{'s' if n != 1 else ''} ha"
                  f"{'s' if n == 1 else 've'} comments on PubPeer:",
                  _table_md(table, ["DOI", "Comments", "PubPeer URL"])]
        summary_text = f"{total} PubPeer comment{'s' if total != 1 else ''}."
    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)


def _pubpeer(doi, timeout=20):
    try:
        r = requests.get(
            f"https://pubpeer.com/v3/publications?devkey=PubPeerZotero&type=doi&doi={doi}",
            timeout=timeout,
            headers={"User-Agent": "ChetaMeck/0.2"})
        if r.status_code != 200:
            return None
        data = r.json()
        pubs = data.get("publications", [])
        if not pubs:
            return None
        pub = pubs[0]
        total = int(pub.get("total_comments", 0) or 0)
        if total <= 0:
            return None
        users = [c.get("users") for c in pub.get("comments", [])]
        users = [u for u in users if u and u != "Statcheck"]
        if not users:
            return None
        return {"total_comments": total,
                "url": f"https://pubpeer.com/publications/{pub.get('id', '')}",
                "users": ", ".join(str(u) for u in users)}
    except Exception:  # noqa: BLE001
        return None


def _table_md(df, headers):
    if df is None or df.empty:
        return "_(no results)_"
    lines = ["| " + " | ".join(headers) + " |",
             "| " + " | ".join(["---"] * len(headers)) + " |"]
    for _, r in df.iterrows():
        cells = [str(r[c]) for c in df.columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)

