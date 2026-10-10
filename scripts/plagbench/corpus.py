"""The plagiarism benchmark corpus: loading, hashing and assembling test cases.

The corpus in ``corpus/`` keeps three things apart and joins them only at run
time, so no assembled manuscript (an adaptation mixing differently licensed
texts) is ever distributed:

* ``hosts_synthetic/*.json`` - manuscripts written for this benchmark (CC0)
* ``hosts_real/*.json``      - unchanged body paragraphs of CC BY articles
* ``passages.json``          - short verbatim excerpts of openly licensed
                               sources, each with full attribution
* ``recipe.json``            - which passage goes where in which host

A *case* is one passage inserted into one host: as a new paragraph
(``paragraph``), or after a given sentence of an existing paragraph
(``sentences3_in_para`` / ``sentence_in_para``).
"""

import hashlib
import json
from pathlib import Path

CORPUS = Path(__file__).resolve().parent / "corpus"
CLASSES = ("pmc", "oa_nonpmc", "psyarxiv", "wikipedia")
TYPES = ("paragraph", "sentences3_in_para", "sentence_in_para")
N_SENTENCES = {"paragraph": 5, "sentences3_in_para": 3, "sentence_in_para": 1}


def _files(root):
    return sorted(list((root / "hosts_synthetic").glob("*.json"))
                  + list((root / "hosts_real").glob("*.json"))
                  + [root / "passages.json", root / "recipe.json"])


def corpus_sha256(root=CORPUS):
    """One hash over all corpus files (names and bytes), to pin a result to it."""
    h = hashlib.sha256()
    for f in _files(root):
        h.update(f.relative_to(root).as_posix().encode())
        h.update(b"\0")
        h.update(f.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def load(root=CORPUS):
    """Return ``(hosts, passages, recipe)``; hosts and passages keyed by id."""
    hosts = {}
    for sub in ("hosts_synthetic", "hosts_real"):
        for f in sorted((root / sub).glob("*.json")):
            h = json.loads(f.read_text(encoding="utf-8"))
            hosts[h["id"]] = h
    passages = {p["id"]: p for p in json.loads(
        (root / "passages.json").read_text(encoding="utf-8"))["passages"]}
    recipe = json.loads((root / "recipe.json").read_text(encoding="utf-8"))
    return hosts, passages, recipe


def assemble(host, cases, passages):
    """Insert the cases' passages into a copy of the host's rows.

    ``cases``: recipe entries of this host, at most one per host row. Returns
    ``(rows, spans)`` with ``spans[case_id] = (row, start, end)`` giving the
    character range of the passage in the assembled rows.
    """
    by_row = {}
    for c in cases:
        assert c["row"] not in by_row, f"two cases in row {c['row']} of {host['id']}"
        by_row[c["row"]] = c
    rows, spans = [], {}
    for i, r in enumerate(host["rows"]):
        c = by_row.get(i)
        if c is None:
            rows.append(dict(r))
            continue
        text = passages[c["passage"]]["text"]
        if c["type"] == "paragraph":            # new paragraph before row i
            spans[c["case_id"]] = (len(rows), 0, len(text))
            rows.append({"header": r["header"], "text": text})
            rows.append(dict(r))
        else:                                   # inside row i, at char ``cut``
            pre, post = r["text"][:c["cut"]].rstrip(), r["text"][c["cut"]:].lstrip()
            new = pre + " " + text + (" " + post if post else "")
            spans[c["case_id"]] = (len(rows), len(pre) + 1, len(pre) + 1 + len(text))
            rows.append({"header": r["header"], "text": new})
    for cid, (row, a, b) in spans.items():
        assert rows[row]["text"][a:b] == passages[
            next(c for c in cases if c["case_id"] == cid)["passage"]]["text"]
    return rows, spans


def host_meta(host):
    """Engine metadata of a host (same-work / own-work detection)."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from plagcheck import core
    return {"title": host["title"], "doi": (host.get("doi") or "").lower(),
            "author_keys": [core.author_key(a.get("family", ""), a.get("given", ""))
                            for a in host.get("authors", [])]}
