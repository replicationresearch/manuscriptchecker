"""Run the live plagiarism benchmark on the corpus in ``corpus/``.

Three tracks, one fixed-seed run per manuscript:

* ``synthetic`` - hosts written for the benchmark, with injected passages.
                  Their text exists nowhere else, so overlap outside the
                  injections is a *candidate false positive* (inspect it).
* ``real``      - CC BY articles with injected passages.
* ``control``   - the same hosts (synthetic and real) without injections;
                  for real hosts this measures *background overlap* (genuine
                  overlap with other papers, including the authors' own).

For every injected passage (a *case*):

* **probed**   - a searched phrase lies completely inside the passage
* **found**    - the true source was among the retrieved candidates
* **verified** - the true source's full text was fetched and overlaps the passage
* **detected** - at least half of the passage's words are covered by verified
                 overlap with any source (the true one or another copy of the
                 text, e.g. the published version of a preprint)

A run is **valid** only if every search of every backend was answered; refused
(allowance used up) or failed searches make it incomplete, because a silent
backend looks like "nothing found". Results are dated observations of live
indexes, not a regression test (those are in ``tests/``).

Usage:
    python scripts/plagbench/run_online.py --openalex-key KEY[,KEY...]
        [--mailto you@example.org] [--hosts syn01 real02] [--no-controls]
"""

import argparse
import json
import math
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))
import plagcheck  # noqa: E402
from plagcheck import core  # noqa: E402
import corpus as C  # noqa: E402

EVALUATOR_VERSION = 2
DETECTED_AT = 0.5       # share of a passage's words that must be covered


# ------------------------------------------------------------------- scoring
def same_source(work, src):
    """Is candidate ``work`` the source a passage was taken from?"""
    if src.get("doi") and work.get("doi") == src["doi"]:
        return True
    if src.get("pmcid") and src["pmcid"] in (work.get("fulltext_id"),
                                             work.get("pmcid")):
        return True
    if src.get("wiki") and (work.get("wiki") or ("", ""))[1] == src["wiki"]:
        return True
    return False


def span_tokens(doc, span, text):
    """Scored token indices of an injected passage in ``doc``."""
    row = doc.rows[span[0]]["text"]
    passage = core.clean_text(text)
    # the occurrence at the recorded insertion point, not an earlier identical
    # stretch of the host (cleaning can shift offsets by a few characters)
    a = row.find(passage, max(0, span[1] - 40))
    if a < 0:
        a = row.find(passage)
    assert a >= 0, text[:60]
    lo = doc.row_offsets[span[0]] + a
    hi = lo + len(passage)
    return [i for i, (s, e) in enumerate(doc.spans)
            if s >= lo and e <= hi and not doc.ignored[i]]


def score_run(r, cases, spans, passages):
    """Per-case rows plus the overlap outside all injections."""
    doc = r["doc"]
    cands = r["sources"] + r["phrase_only"] + r["compared_no_match"] + r["same_work"]
    starts = {c["gstart"] for c in r["phrases"]}
    injected = set()
    out = []
    for c in cases:
        p = passages[c["passage"]]
        toks = span_tokens(doc, spans[c["case_id"]], p["text"])
        tset = set(toks)
        injected |= tset
        true_verified = [s for s in r["sources"] if same_source(s, p["source"])]
        cov = sum(1 for t in toks if r["union"][t]) / max(len(toks), 1)
        cov_true = sum(1 for t in toks if any(s["covered"][t] for s in true_verified)) \
            / max(len(toks), 1)
        out.append({
            "case_id": c["case_id"], "host": c["host"], "class": p["class"],
            "type": c["type"], "words": len(toks),
            "probed": any(all(g + k in tset for k in range(core.PHRASE_WORDS))
                          for g in starts),
            "found": any(same_source(w, p["source"]) for w in cands),
            "verified": cov_true >= DETECTED_AT,
            "coverage": round(cov, 3), "detected": cov >= DETECTED_AT})
    outside = [i for i in range(len(doc.words))
               if i not in injected and not doc.ignored[i]]
    flagged = []
    for s in r["sources"]:
        n = sum(1 for i in outside if s["covered"][i])
        if n:
            flagged.append({"title": (s.get("title") or s.get("name") or "")[:120],
                            "doi": s.get("doi") or "", "words": n,
                            "own_work": bool(s.get("own_work")),
                            "cited": bool(s.get("cited"))})
    own = [False] * len(doc.words)
    for s in r["sources"]:
        if s.get("own_work"):
            own = [a or b for a, b in zip(own, s["covered"])]
    return out, {
        "words_outside": len(outside),
        "flagged_outside": sum(1 for i in outside if r["union"][i]),
        "flagged_outside_own_work": sum(1 for i in outside if own[i]),
        "flagged_outside_other": sum(1 for i in outside if r["union"][i] and not own[i]),
        "sources_outside": sorted(flagged, key=lambda x: -x["words"])}


def wilson(k, n, z=1.96):
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def table(rows, key):
    groups = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    if len(groups) > 1:
        groups["ALL"] = rows
    lines = [f"{key:20s} {'n':>3s} {'probed':>8s} {'found':>8s} {'verified':>9s} "
             f"{'detected':>9s}  95% interval (detected)"]
    for g, rs in groups.items():
        n = len(rs)
        k = sum(r["detected"] for r in rs)
        lo, hi = wilson(k, n)
        lines.append(
            f"{g:20s} {n:3d} {sum(r['probed'] for r in rs):5d}/{n:<2d} "
            f"{sum(r['found'] for r in rs):5d}/{n:<2d} "
            f"{sum(r['verified'] for r in rs):6d}/{n:<2d} {k:6d}/{n:<2d}  "
            f"{k / n:4.0%} [{lo:.0%}-{hi:.0%}]")
    return "\n".join(lines)


def git_state():
    def run(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True,
                              text=True).stdout.strip()
    import hashlib
    h = hashlib.sha256()        # identifies the engine even with local changes
    for f in sorted((ROOT / "plagcheck").glob("*.py")) + [Path(__file__)]:
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    return {"commit": run("rev-parse", "HEAD"), "code_sha256": h.hexdigest(),
            "dirty": bool(run("status", "--porcelain", "--", "plagcheck"))}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--openalex-key", default=None,
                    help="one or several comma-separated OpenAlex API keys")
    ap.add_argument("--mailto", default=None)
    ap.add_argument("--hosts", nargs="*", help="host ids (default: all)")
    ap.add_argument("--no-controls", action="store_true")
    ap.add_argument("--backends", nargs="+", default=list(core.BACKENDS))
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--dry-run", action="store_true",
                    help="only count the searches the run would send")
    args = ap.parse_args()
    hosts, passages, recipe = C.load()
    options = {"seed": args.seed, "phrase_log": False, "mailto": args.mailto,
               "backends": tuple(args.backends)}
    shown = dict(plagcheck.DEFAULT_OPTIONS, **options)

    runs = []           # (track, host, cases)
    for h in hosts.values():
        if args.hosts and h["id"] not in args.hosts:
            continue
        cases = [c for c in recipe["cases"] if c["host"] == h["id"]]
        runs.append((h["kind"], h, cases))
        if not args.no_controls:
            runs.append(("control", h, []))

    # searches needed: one per selected phrase and backend
    n_phrases = 0
    for _, h, cases in runs:
        rows, _ = C.assemble(h, cases, passages)
        doc = core.Doc(rows)
        sel, _ = core.select_phrases(core.eligible_phrases(doc), args.seed, None, 0,
                                     shown["words_per_probe"])
        n_phrases += len(sel)
    n_keys = len((args.openalex_key or "").split(",")) if args.openalex_key else 0
    print(f"{len(runs)} runs, {n_phrases} phrases per backend; OpenAlex combines "
          f"up to {core.OA_MAX_BATCH} phrases per metered search (roughly "
          f"{n_phrases // 12} searches; allowance about "
          f"{1000 * n_keys if n_keys else 100}/day with {n_keys} key(s)).",
          flush=True)
    if args.dry_run:
        return

    t0 = time.time()
    case_rows, host_rows = [], []
    totals = defaultdict(lambda: {"ok": 0, "failed": 0, "quota": 0, "requests": 0})
    for track, h, cases in runs:
        rows, spans = C.assemble(h, cases, passages)
        r = plagcheck.check_document(
            rows, C.host_meta(h), dict(options, openalex_key=args.openalex_key))
        scored, outside = score_run(r, cases, spans, passages)
        for row in scored:
            row["track"] = track
        case_rows += scored
        for name, st in r["search_stats"].items():
            for k in st:
                totals[name][k] += st[k]
        host_rows.append(dict(
            host=h["id"], track=track, phrases=r["n_phrases"],
            score=round(r["score"], 4), sources_verified=len(r["sources"]),
            candidates_not_fetched=len(r["phrase_only"]),
            same_work_dropped=len(r["same_work"]),
            search_stats=r["search_stats"], **outside))
        print(f"{track:9s} {h['id']}: detected "
              f"{sum(x['detected'] for x in scored)}/{len(scored)}, flagged outside "
              f"injections {outside['flagged_outside']}/{outside['words_outside']} "
              f"[{time.time() - t0:.0f}s]", flush=True)

    valid = all(st["failed"] == 0 and st["quota"] == 0 for st in totals.values())
    stamp = time.strftime("%Y-%m-%dT%H:%MZ", time.gmtime())
    git = git_state()
    prov = {"utc": stamp, "valid": valid, "evaluator_version": EVALUATOR_VERSION,
            "corpus_sha256": C.corpus_sha256(), "corpus_version": recipe["version"],
            "engine_version": plagcheck.PLAG_APP_VERSION, "engine_commit": git["commit"],
            "engine_dirty": git["dirty"], "code_sha256": git["code_sha256"],
            "python": sys.version.split()[0],
            "requests": __import__("requests").__version__,
            "options": {k: (v if not isinstance(v, tuple) else list(v))
                        for k, v in shown.items() if k not in ("mailto",)},
            "detected_at": DETECTED_AT, "searches": dict(totals)}

    rep = [f"# Online benchmark - {stamp}",
           "",
           f"Run {'VALID' if valid else 'INCOMPLETE - searches failed or were refused'}"
           f"; corpus {prov['corpus_sha256'][:12]} (v{recipe['version']}); engine "
           f"{prov['engine_version']} @ {git['commit'][:8]}"
           f"{' + uncommitted changes' if git['dirty'] else ''} (code "
           f"{git['code_sha256'][:12]}); one run per "
           f"manuscript, seed {args.seed}, one phrase per "
           f"{shown['words_per_probe']} words.",
           "",
           "Phrases answered / failed / refused for quota (requests sent):"]
    rep += [f"  {n}: {st['ok']} / {st['failed']} / {st['quota']} ({st['requests']})"
            for n, st in totals.items()]
    rep += ["",
            "Counts are cases (injected passages). Intervals are Wilson 95% "
            "intervals that treat cases as independent; cases share hosts, so "
            "read them as descriptive. This is a pilot-sized corpus."]
    for track in ("synthetic", "real"):
        rows = [r for r in case_rows if r["track"] == track]
        if rows:
            rep += ["", f"## {track.capitalize()} hosts", "", table(rows, "class"),
                    "", table(rows, "type")]
    if case_rows:
        rep += ["", "## Both tracks", "", table(case_rows, "class"), "",
                table(case_rows, "type")]
    rep += ["", "## Overlap outside the injections", ""]
    for label, sel in (
            ("synthetic hosts with injections (candidate false positives)",
             lambda x: x["track"] == "synthetic"),
            ("real hosts with injections (background overlap)",
             lambda x: x["track"] == "real"),
            ("controls, synthetic (candidate false positives)",
             lambda x: x["track"] == "control" and x["host"].startswith("syn")),
            ("controls, real (background overlap)",
             lambda x: x["track"] == "control" and not x["host"].startswith("syn"))):
        hs = [x for x in host_rows if sel(x)]
        if not hs:
            continue
        n = sum(x["words_outside"] for x in hs)
        f = sum(x["flagged_outside"] for x in hs)
        o = sum(x["flagged_outside_own_work"] for x in hs)
        rep.append(f"{label}: {f}/{n} words ({f / max(n, 1):.2%}); of these {o} "
                   f"from the authors' own prior work, "
                   f"{sum(x['flagged_outside_other'] for x in hs)} from other sources")
        for x in hs:
            for s in x["sources_outside"][:6]:
                rep.append(f"    {x['host']}: {s['words']:4d} words - "
                           f"{'[own work] ' if s['own_work'] else ''}{s['title'][:80]}")
    nf = sum(x["candidates_not_fetched"] for x in host_rows)
    rep += ["", f"Candidates whose full text was not compared (download failed "
                f"or beyond the per-run limit): {nf}"]
    text = "\n".join(rep)
    print("\n" + text)
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    stem = time.strftime("%Y%m%d_%H%M", time.gmtime()) + ("" if valid else "_incomplete")
    (out / f"{stem}.txt").write_text(text + "\n", encoding="utf-8")
    (out / f"{stem}.json").write_text(json.dumps(
        {"provenance": prov, "cases": case_rows, "hosts": host_rows}, indent=1),
        encoding="utf-8")


if __name__ == "__main__":
    main()
