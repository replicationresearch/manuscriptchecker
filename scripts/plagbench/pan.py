"""Evaluate the verbatim matcher on the PAN13 text-alignment corpus.

Matcher only: this tests the text-alignment stage (``core.match_doc`` +
normalisation). PAN source documents are books, not open scholarly full texts,
so retrieval is out of scope here (see ``run_online.py`` for that).

The measures are our own implementation of the PAN-style character-level
measures (Potthast et al., 2010: precision, recall, granularity, plagdet). They
are checked against hand-calculated cases in ``tests/`` but NOT validated
against the official PAN scorer, so do not compare the numbers directly with
published PAN scores.

The corpus is not in this repository. Download once (about 30 MB):
    https://zenodo.org/records/3715980/files/pan13-text-alignment-test-and-training.zip
    sha256 82b48527058ee2610e77360ff0d38d28fa54abfa7fa50e34d84673065524d223
Unzip it, then unzip the contained
    pan13-text-alignment-test-corpus2-2013-01-21.zip
    sha256 933eff7e73308682237d354289f9fb093da0ef1eb5ff065707a7834c4638c507

Usage:
    python scripts/plagbench/pan.py PATH/TO/pan13-text-alignment-test-corpus2-2013-01-21
        [--subsets 01-no-plagiarism 02-no-obfuscation 03-random-obfuscation]
        [--no-exclusions]

The verbatim task is ``01`` + ``02``; ``03`` (random word swaps and
replacements) is shown for reference only - this engine deliberately ignores
reworded text.
"""

import argparse
import math
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from plagcheck import core  # noqa: E402


def clean_with_map(text):
    """``core.clean_text`` plus a map cleaned-offset -> original offset."""
    out, mp = [], []
    i = 0
    while i < len(text):        # base character plus its combining marks
        j = i + 1
        while j < len(text) and unicodedata.combining(text[j]):
            j += 1
        n = unicodedata.normalize("NFKC", text[i:j])
        out.append(n)
        mp.extend([i] * len(n))
        i = j
    s = "".join(out)
    res, m2, last = [], [], 0
    for m in core._LINEBREAK_HYPHEN.finditer(s):
        res.append(s[last:m.start()])
        m2.extend(mp[last:m.start()])
        res.append("-")
        m2.append(mp[m.start()])
        last = m.end()
    res.append(s[last:])
    m2.extend(mp[last:])
    keep = [(c, o) for c, o in zip("".join(res), m2) if c != "­"]
    s = "".join(c for c, _ in keep)
    return s, [o for _, o in keep] + [len(text)]


def _orig_span(mp, a, b):
    return mp[a], mp[b - 1] + 1


def detect(doc, dmap, src_text, exclusions=True):
    """Detections [(susp_start, susp_end, src_start, src_end)] in original offsets."""
    s_clean, smap = clean_with_map(src_text)
    toks = core.tokenize(s_clean)
    _, runs = core.match_doc(doc, [w for w, _, _ in toks])
    out = []
    for i, j, p in runs:
        a, b = _orig_span(dmap, doc.spans[i][0], doc.spans[j - 1][1])
        q = min(p + (j - i), len(toks)) - 1
        c, d = _orig_span(smap, toks[p][1], toks[q][2])
        out.append((a, b, c, d))
    return out


def load_cases(xml_path):
    root = ET.parse(xml_path).getroot()
    cases = []
    for f in root.iter("feature"):
        if f.get("name") != "plagiarism":
            continue
        a, la = int(f.get("this_offset")), int(f.get("this_length"))
        c, lc = int(f.get("source_offset")), int(f.get("source_length"))
        cases.append((a, a + la, c, c + lc))
    return cases


def _overlap(x0, x1, y0, y1):
    return max(0, min(x1, y1) - max(x0, y0))


def _union_len(intervals):
    total, end = 0, None
    for a, b in sorted(intervals):
        if end is None or a > end:
            total += b - a
            end = b
        elif b > end:
            total += b - end
            end = b
    return total


def pan_measures(pairs):
    """pairs: [(cases, detections)] -> dict(precision, recall, granularity, plagdet)."""
    n_s = n_r = 0
    rec_sum = prec_sum = 0.0
    gran_sum, n_detected = 0, 0
    for cases, dets in pairs:
        def detects(r, s):
            return (_overlap(r[0], r[1], s[0], s[1]) > 0
                    and _overlap(r[2], r[3], s[2], s[3]) > 0)
        for s in cases:
            n_s += 1
            rs = [r for r in dets if detects(r, s)]
            if rs:
                n_detected += 1
                gran_sum += len(rs)
            hit_susp = _union_len([(max(r[0], s[0]), min(r[1], s[1]))
                                   for r in rs if _overlap(r[0], r[1], s[0], s[1])])
            hit_src = _union_len([(max(r[2], s[2]), min(r[3], s[3]))
                                  for r in rs if _overlap(r[2], r[3], s[2], s[3])])
            rec_sum += (hit_susp + hit_src) / ((s[1] - s[0]) + (s[3] - s[2]))
        for r in dets:
            n_r += 1
            ss = [s for s in cases if detects(r, s)]
            hit_susp = _union_len([(max(r[0], s[0]), min(r[1], s[1])) for s in ss])
            hit_src = _union_len([(max(r[2], s[2]), min(r[3], s[3])) for s in ss])
            prec_sum += (hit_susp + hit_src) / max((r[1] - r[0]) + (r[3] - r[2]), 1)
    rec = rec_sum / n_s if n_s else float("nan")
    prec = prec_sum / n_r if n_r else 1.0
    gran = gran_sum / n_detected if n_detected else 1.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"precision": prec, "recall": rec, "granularity": gran,
            "plagdet": f1 / math.log2(1 + gran), "cases": n_s,
            "detections": n_r, "cases_detected": n_detected}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("corpus")
    ap.add_argument("--subsets", nargs="+",
                    default=["01-no-plagiarism", "02-no-obfuscation",
                             "03-random-obfuscation"])
    ap.add_argument("--no-exclusions", action="store_true",
                    help="do not exclude quotes / citations (pure alignment)")
    args = ap.parse_args()
    root = Path(args.corpus)
    docs = {}
    results = {}
    for sub in args.subsets:
        pairs = []
        for line in (root / sub / "pairs").read_text().split("\n"):
            if not line.strip():
                continue
            susp, src = line.split()
            if susp not in docs:
                text = (root / "susp" / susp).read_text(encoding="utf-8")
                clean, dmap = clean_with_map(text)
                doc = core.Doc([{"header": "", "text": clean}])
                assert doc.text == clean, susp
                if args.no_exclusions:
                    doc.ignored = [False] * len(doc.words)
                    doc.n_scored = len(doc.words)
                docs[susp] = (doc, dmap)
            doc, dmap = docs[susp]
            src_text = (root / "src" / src).read_text(encoding="utf-8")
            xml = root / sub / f"{susp[:-4]}-{src[:-4]}.xml"
            pairs.append((load_cases(xml), detect(doc, dmap, src_text)))
        results[sub] = pairs
        m = pan_measures(pairs)
        fp = sum(len(d) for c, d in pairs if not c)
        print(f"{sub:24s} pairs={len(pairs):5d} cases={m['cases']:5d} "
              f"detected={m['cases_detected']:5d} recall={m['recall']:.3f} "
              f"precision={m['precision']:.3f} gran={m['granularity']:.3f} "
              f"plagdet={m['plagdet']:.3f} detections_in_negative_pairs={fp}",
              flush=True)
    verbatim = [p for s in ("01-no-plagiarism", "02-no-obfuscation")
                if s in results for p in results[s]]
    if verbatim:
        m = pan_measures(verbatim)
        print(f"{'verbatim task (01+02)':24s} recall={m['recall']:.3f} "
              f"precision={m['precision']:.3f} gran={m['granularity']:.3f} "
              f"plagdet={m['plagdet']:.3f}")


if __name__ == "__main__":
    main()
