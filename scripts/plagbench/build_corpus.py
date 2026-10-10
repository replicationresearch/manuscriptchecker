"""Build the benchmark corpus in ``corpus/`` (run once; the result is committed).

Writes ``hosts_real/*.json``, ``passages.json``, ``recipe.json`` and
``NOTICE.md``. The synthetic hosts in ``hosts_synthetic/`` are written by hand
and only read here. See ``corpus.py`` for the layout.

Every third-party text is licence-checked on the version actually fetched:

* PubMed Central   - the permissions block of the article XML must name
                     CC BY, CC BY-SA or CC0 with a version
* open access outside PMC - the OpenAlex location that was downloaded must be
                     CC BY / CC BY-SA, and the PDF's own licence statement
                     (first or last pages) must name the same licence and version
* PsyArXiv         - licence of the preprint in the OSF API must be CC BY / CC0
* Wikipedia        - CC BY-SA 4.0, pinned to a revision

Sources that fail the check are skipped, never stored by identifier only.

Usage:
    python scripts/plagbench/build_corpus.py --openalex-key KEY
        [--per-cell 6] [--real-hosts 6] [--seed 7] [--mailto you@example.org]
"""

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from plagcheck import core  # noqa: E402
import corpus as C  # noqa: E402

EPMC = "https://www.ebi.ac.uk/europepmc/webservices/rest/"
WIKI = "https://en.wikipedia.org/w/api.php"
OSF = "https://api.osf.io/v2/"
CHANGE_NOTICE = ("Verbatim excerpt; whitespace collapsed and PDF line-end "
                 "hyphenation removed.")
_CC_URL = re.compile(r"creativecommons\.org/(?:licenses/(by(?:-sa)?)/(\d\.\d)|"
                     r"(publicdomain/zero)/1\.0)", re.I)
_CC_TEXT = re.compile(r"Creative\s+Commons\s+Attribution(?:[-\s]+(Share[-\s]?Alike))?"
                      r"(?:\s+(\d\.\d))?", re.I)
_NC_ND = re.compile(r"non-?commercial|no-?deriv|by-nc|by-nd", re.I)


def parse_cc(text):
    """``(name, url)`` of the Creative Commons licence stated in ``text``.

    Only CC BY, CC BY-SA and CC0 with an explicit version are accepted; a
    statement that also mentions NonCommercial / NoDerivatives, or that gives
    no version, returns None (the source is then not used).
    """
    if not text or _NC_ND.search(text):
        return None
    m = _CC_URL.search(text)
    if m and m.group(3):
        return "CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/"
    if m:
        kind, ver = m.group(1).lower(), m.group(2)
    else:
        m = _CC_TEXT.search(text)
        if not m or not m.group(2):
            return None
        kind, ver = ("by-sa" if m.group(1) else "by"), m.group(2)
    return (f"CC {kind.upper()} {ver}",
            f"https://creativecommons.org/licenses/{kind}/{ver}/")


WIKI_TITLES = [
    "Cognitive dissonance", "Attachment theory", "Confirmation bias",
    "Self-determination theory", "Stereotype threat", "Bystander effect",
    "Working memory", "Big Five personality traits", "Dunning–Kruger effect",
    "Social identity theory", "Learned helplessness", "Placebo",
    "Cognitive behavioral therapy", "Replication crisis", "Implicit stereotype",
    "Theory of planned behavior", "Mindfulness", "Procrastination",
    "Groupthink", "Flow (psychology)", "Loneliness", "Emotional intelligence",
    "Social loafing", "Ego depletion", "Anchoring effect", "Framing effect",
    "Self-efficacy", "Locus of control", "Hindsight bias", "Mere-exposure effect",
]
_SENT_SPLIT = re.compile(r"(?<=[a-z\)][.!?])\s+(?=[A-Z])")


# ------------------------------------------------------------------ passages
def good_sentence(s):
    toks = s.split()
    if not 12 <= len(toks) <= 60:
        return False
    if re.search(r"https?:|doi|www\.|©|\bet al\b|\bTable\b|\bFigure\b|\bFig\.", s):
        return False
    alpha = sum(1 for t in toks if re.fullmatch(r"[A-Za-z][A-Za-z'’,;:\-()]*\.?", t))
    if alpha / len(toks) < 0.85:
        return False
    words = [w.lower().strip(".,;:()") for w in toks]
    return sum(1 for w in words if w in core.STOP) / len(words) >= 0.25   # English


def sentences(text):
    return _SENT_SPLIT.split(" ".join(core.clean_text(text).split()))


def pick_passage(text, kind, rng):
    """A run of good English sentences from the middle of ``text`` (or None)."""
    sents = sentences(text)
    lo, hi = int(len(sents) * 0.15), int(len(sents) * 0.75)
    want = C.N_SENTENCES[kind]
    starts = list(range(lo, max(lo, hi - want)))
    rng.shuffle(starts)
    for i in starts:
        run = sents[i:i + want]
        if len(run) == want and all(good_sentence(s) for s in run):
            return " ".join(run)
    return None


# -------------------------------------------------------------- Europe PMC
def epmc_search(s, query, rng):
    r = s.get(EPMC + "search", params={"query": query, "format": "json",
                                       "pageSize": 300, "resultType": "core"},
              timeout=60).json()
    res = [x for x in r["resultList"]["result"] if x.get("pmcid") and x.get("doi")]
    rng.shuffle(res)
    return res


def epmc_article(s, pmcid):
    """(paragraph rows, body text, licence dict or None) from the article XML."""
    from lxml import etree
    r = s.get(EPMC + f"{pmcid}/fullTextXML", timeout=60)
    if r.status_code != 200:
        return [], "", None
    root = etree.fromstring(r.content, etree.XMLParser(recover=True))
    if root is None:
        return [], "", None
    perm = root.find(".//permissions")
    lic = None
    if perm is not None:
        # tostring keeps the licence URI of <license xlink:href="...">
        cc = parse_cc(etree.tostring(perm, encoding="unicode"))
        if cc:
            lic = {"license": cc[0], "license_url": cc[1],
                   "copyright": (perm.findtext("copyright-statement") or "").strip(),
                   "license_statement": " ".join(
                       "".join(perm.itertext()).split())[:400]}
    body = root.find(".//body")
    if body is None:
        return [], "", lic
    # with_tail=False: the text after a removed element belongs to the paragraph
    etree.strip_elements(body, "table-wrap", "fig", "ref-list", with_tail=False)
    rows = []
    for sec in body.iter("sec"):
        title = " ".join((sec.findtext("title") or "").split())
        for p in sec.findall("p"):
            t = " ".join("".join(p.itertext()).split())
            if t:
                rows.append({"header": title, "text": t})
    return rows, " ".join(r["text"] for r in rows), lic


def _epmc_authors(x):
    return [{"family": a.get("lastName", ""), "given": a.get("firstName", "")}
            for a in (x.get("authorList") or {}).get("author", [])
            if a.get("lastName")]


def _creators(authors):
    names = [f"{a['given']} {a['family']}".strip() for a in authors]
    return ", ".join(names[:6]) + (" et al." if len(names) > 6 else "")


def real_hosts(s, n, rng, used):
    q = ('(ABSTRACT:"participants" AND (ABSTRACT:"survey" OR '
         'ABSTRACT:"questionnaire")) AND IN_PMC:y AND OPEN_ACCESS:y AND '
         'LICENSE:"cc by" AND PUB_YEAR:[2016 TO 2024]')
    out = []
    for x in epmc_search(s, q, rng):
        rows, _, lic = epmc_article(s, x["pmcid"])
        words = sum(len(r["text"].split()) for r in rows)
        if not lic or not 1800 <= words <= 4500 or \
                sum(1 for r in rows if len(r["text"].split()) >= 60) < 12:
            continue
        used.add(x["pmcid"])
        authors = _epmc_authors(x)
        out.append(dict(
            id=f"real{len(out) + 1:02d}", kind="real", title=x["title"].rstrip("."),
            doi=x["doi"].lower(), pmcid=x["pmcid"], authors=authors, language="en",
            source_url=f"https://europepmc.org/article/PMC/{x['pmcid'][3:]}",
            creators=_creators(authors), retrieved=time.strftime("%Y-%m-%d"),
            change_notice="Body paragraphs unchanged; tables, figures and the "
                          "reference list removed.",
            rows=rows, **lic))
        print(f"  host {x['pmcid']}: {x['title'][:70]}", flush=True)
        if len(out) >= n:
            break
    return out


def pmc_sources(s, n, rng, used):
    q = ('(ABSTRACT:"participants" AND (ABSTRACT:"psychology" OR '
         'ABSTRACT:"behaviour" OR ABSTRACT:"behavior")) AND IN_PMC:y AND '
         'OPEN_ACCESS:y AND LICENSE:"cc by" AND PUB_YEAR:[2016 TO 2024]')
    for x in epmc_search(s, q, rng):
        if x["pmcid"] in used:
            continue
        _, text, lic = epmc_article(s, x["pmcid"])
        if not lic or len(text) < 8000:
            continue
        used.add(x["pmcid"])
        yield dict(text=text, title=x["title"].rstrip("."), doi=x["doi"].lower(),
                   pmcid=x["pmcid"], creators=_creators(_epmc_authors(x)),
                   url=f"https://europepmc.org/article/PMC/{x['pmcid'][3:]}", **lic)


# ----------------------------------------------------------------- OpenAlex
def openalex_sample(s, flt, n, seed, key, mailto):
    params = {"filter": flt, "sample": n, "seed": seed, "per-page": n,
              "select": "id,doi,title,language,authorships,locations,ids",
              "api_key": key}
    if mailto:
        params["mailto"] = mailto
    r = s.get("https://api.openalex.org/works", params=params, timeout=60)
    r.raise_for_status()
    return r.json().get("results", [])


def _oa_authors(w):
    out = []
    for a in w.get("authorships") or []:
        parts = (a.get("author", {}).get("display_name") or "").split()
        if parts:
            out.append({"family": parts[-1], "given": " ".join(parts[:-1])})
    return out


def oa_nonpmc_sources(s, seed, key, mailto):
    """Open-access psychology articles outside PMC, CC BY / BY-SA / CC0 at the
    downloaded location and in the PDF's own licence statement."""
    ok = {"cc-by": "CC BY", "cc-by-sa": "CC BY-SA"}
    flt = ("primary_topic.field.id:32,type:article,open_access.is_oa:true,"
           "has_pmcid:false,language:en,publication_year:2015-2024,"
           "best_oa_location.license:cc-by|cc-by-sa")
    for w in openalex_sample(s, flt, 200, seed, key, mailto):
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        for loc in w.get("locations") or []:
            if not doi or loc.get("license") not in ok or not loc.get("pdf_url"):
                continue
            text = core.fetch_source_text(s, {"urls": [loc["pdf_url"]]})
            if len(text) < 8000:
                continue
            # the PDF's own licence statement (title page or end matter, not a
            # reference) must name the same licence, with its version
            def stated(region):     # PDF text may break a licence URL across lines
                return parse_cc(region) or parse_cc(re.sub(r"\s+", "", region))
            cc = stated(text[:6000]) or stated(text[-6000:])
            if not cc or cc[0].rsplit(" ", 1)[0] != ok[loc["license"]]:
                continue
            name = cc[0]
            yield dict(text=text, title=(w.get("title") or "").rstrip("."), doi=doi,
                       creators=_creators(_oa_authors(w)),
                       url=loc.get("landing_page_url") or "https://doi.org/" + doi,
                       file_url=loc["pdf_url"], license=name, license_url=cc[1],
                       license_statement="Licence stated in the downloaded PDF "
                                         "and in OpenAlex for this location.")
            break


def psyarxiv_sources(s, seed, key, mailto):
    ok = {"CC-By Attribution 4.0 International":
          ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/"),
          "CC0 1.0 Universal":
          ("CC0 1.0", "https://creativecommons.org/publicdomain/zero/1.0/")}
    flt = "doi_starts_with:10.31234,language:en,publication_year:2018-2024"
    for w in openalex_sample(s, flt, 200, seed, key, mailto):
        doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
        m = re.search(r"osf\.io/([a-z0-9]{5,6})", doi)
        if not m:
            continue
        r = s.get(OSF + f"preprints/{m.group(1)}/", params={"embed": "license"},
                  timeout=30)
        if r.status_code != 200:
            continue
        d = r.json()["data"]
        lic = ((d.get("embeds", {}).get("license", {}).get("data") or {})
               .get("attributes", {}).get("name"))
        if lic not in ok:
            continue
        text = core.fetch_source_text(s, {"urls": [f"https://osf.io/download/{d['id']}/"]})
        if len(text) < 8000:
            continue
        cr = s.get(d["relationships"]["contributors"]["links"]["related"]["href"],
                   params={"embed": "users", "filter[bibliographic]": "true"},
                   timeout=30).json()
        authors = [{"family": u["embeds"]["users"]["data"]["attributes"]["family_name"],
                    "given": u["embeds"]["users"]["data"]["attributes"]["given_name"]}
                   for u in cr.get("data", []) if "data" in u["embeds"]["users"]]
        name, lic_url = ok[lic]
        yield dict(text=text, title=d["attributes"]["title"].rstrip("."), doi=doi,
                   creators=_creators(authors),
                   url=f"https://osf.io/preprints/psyarxiv/{d['id']}",
                   file_url=f"https://osf.io/download/{d['id']}/", license=name,
                   license_url=lic_url,
                   license_statement=f"OSF preprint licence: {lic} (version {d['id']}).")


def wikipedia_sources(s, rng):
    titles = list(WIKI_TITLES)
    rng.shuffle(titles)
    for t in titles:
        j = s.get(WIKI, params={"action": "query", "prop": "extracts|revisions",
                                "explaintext": 1, "rvprop": "ids|timestamp",
                                "titles": t, "format": "json", "formatversion": 2},
                  timeout=60).json()
        p = j["query"]["pages"][0]
        text, rev = p.get("extract", ""), (p.get("revisions") or [{}])[0]
        if len(text) < 8000 or not rev.get("revid"):
            continue
        slug = p["title"].replace(" ", "_")
        yield dict(text=text, title=p["title"], wiki=p["title"],
                   creators="Wikipedia contributors",
                   url=f"https://en.wikipedia.org/w/index.php?title={slug}"
                       f"&oldid={rev['revid']}",
                   history_url=f"https://en.wikipedia.org/w/index.php?title={slug}"
                               "&action=history",
                   revision=rev["revid"], license="CC BY-SA 4.0",
                   license_url="https://creativecommons.org/licenses/by-sa/4.0/",
                   license_statement="Wikipedia text is available under the "
                                     "Creative Commons Attribution-ShareAlike "
                                     "4.0 License.")


# -------------------------------------------------------------------- recipe
def place(host, kind, rng, taken):
    """Row (and sentence cut) where a passage goes in ``host``."""
    body = [i for i, r in enumerate(host["rows"])
            if len(r["text"].split()) >= 60 and i >= 2 and i not in taken
            and not core.DECLARATION_RE.search(r.get("header") or "")]
    i = rng.choice(body)
    if kind == "paragraph":
        return i, None
    cuts = [m.start() for m in _SENT_SPLIT.finditer(host["rows"][i]["text"])]
    return i, (rng.choice(cuts) if cuts else len(host["rows"][i]["text"]))


def notice(hosts_real, passages):
    lines = [
        "# Benchmark corpus: sources and licences", "",
        "The synthetic hosts in `hosts_synthetic/` were written for this "
        "benchmark and are dedicated to the public domain (CC0 1.0).", "",
        "The texts below are third-party works, reused under their licences. "
        "Each is stored unchanged apart from the change noted. The benchmark "
        "joins hosts and passages only in memory; no combined text is "
        "distributed. Wikipedia excerpts are CC BY-SA 4.0 and remain so in any "
        "copy of `passages.json`.", "", "## Real hosts", ""]
    for h in hosts_real:
        lines.append(f"- **{h['id']}** - {h['creators']}. *{h['title']}*. "
                     f"https://doi.org/{h['doi']} ({h['source_url']}). "
                     f"{h['copyright']}. Licence: [{h['license']}]({h['license_url']}). "
                     f"{h['change_notice']}")
    lines += ["", "## Passages", "", CHANGE_NOTICE, ""]
    for p in passages:
        src = p["source"]
        ref = f"https://doi.org/{src['doi']}" if src.get("doi") else src["url"]
        lines.append(f"- **{p['id']}** - {src['creators']}. *{src['title']}*. {ref}"
                     + (f" (revision {src['revision']}, {src['url']}; history: "
                        f"{src['history_url']})" if src.get("revision") else
                        f" ({src['url']})" if src.get("doi") else "")
                     + f". Licence: [{src['license']}]({src['license_url']}).")
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--openalex-key", required=True)
    ap.add_argument("--per-cell", type=int, default=6,
                    help="passages per source class x insertion type")
    ap.add_argument("--real-hosts", type=int, default=6)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mailto", default=None)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    s = requests.Session()
    s.headers["User-Agent"] = core.UA + (f" mailto:{args.mailto}" if args.mailto else "")
    key = args.openalex_key.split(",")[0]

    synthetic = [json.loads(f.read_text(encoding="utf-8"))
                 for f in sorted((C.CORPUS / "hosts_synthetic").glob("*.json"))]
    assert synthetic, "write the synthetic hosts first"
    print("Real hosts (PMC, CC BY)...", flush=True)
    used = set()
    hosts_real = real_hosts(s, args.real_hosts, rng, used)
    hosts = synthetic + hosts_real
    n_cells = len(hosts) * 6
    assert n_cells == len(C.CLASSES) * len(C.TYPES) * args.per_cell, \
        "hosts x 6 must equal classes x types x per-cell"

    print("Passages...", flush=True)
    gens = {"pmc": pmc_sources(s, 0, rng, used),
            "oa_nonpmc": oa_nonpmc_sources(s, args.seed, key, args.mailto),
            "psyarxiv": psyarxiv_sources(s, args.seed, key, args.mailto),
            "wikipedia": wikipedia_sources(s, rng)}
    passages, tried = [], {c: 0 for c in C.CLASSES}
    for cls in C.CLASSES:
        kinds = [k for k in C.TYPES for _ in range(args.per_cell)]
        for src in gens[cls]:
            if not kinds:
                break
            tried[cls] += 1
            text = pick_passage(src.pop("text"), kinds[0], rng)
            if not text:
                continue
            kind = kinds.pop(0)
            n = sum(1 for p in passages if p["class"] == cls) + 1
            src.update(retrieved=time.strftime("%Y-%m-%d"), change_notice=CHANGE_NOTICE)
            passages.append({"id": f"{cls}-{n:02d}", "class": cls, "type": kind,
                             "language": "en", "text": text, "source": src})
            print(f"  {cls}-{n:02d} {kind}: {src['title'][:60]}", flush=True)
        assert not kinds, f"not enough usable {cls} sources"

    # each track (synthetic / real) gets every class x type cell equally often
    cases = []
    for track in (synthetic, hosts_real):
        cells = [(c, t) for c in C.CLASSES for t in C.TYPES
                 for _ in range(args.per_cell // 2)]
        rng.shuffle(cells)
        for h_idx, host in enumerate(track):
            taken = set()
            for cls, kind in cells[h_idx * 6:(h_idx + 1) * 6]:
                p = next(p for p in passages if p["class"] == cls and p["type"] == kind
                         and p["id"] not in {c["passage"] for c in cases})
                row, cut = place(host, kind, rng, taken)
                taken.add(row)
                cases.append({"case_id": f"{host['id']}:{p['id']}", "host": host["id"],
                              "passage": p["id"], "type": kind, "row": row, "cut": cut})

    for h in hosts_real:
        (C.CORPUS / "hosts_real").mkdir(exist_ok=True)
        (C.CORPUS / "hosts_real" / f"{h['id']}.json").write_text(
            json.dumps(h, ensure_ascii=False, indent=1), encoding="utf-8")
    (C.CORPUS / "passages.json").write_text(json.dumps(
        {"passages": passages}, ensure_ascii=False, indent=1), encoding="utf-8")
    (C.CORPUS / "recipe.json").write_text(json.dumps(
        {"version": 2, "seed": args.seed, "built": time.strftime("%Y-%m-%d"),
         "sources_tried": tried, "cases": cases}, indent=1), encoding="utf-8")
    (C.CORPUS / "NOTICE.md").write_text(notice(hosts_real, passages), encoding="utf-8")
    hosts_d, passages_d, recipe = C.load()
    for h in hosts_d.values():          # the recipe must assemble
        C.assemble(h, [c for c in recipe["cases"] if c["host"] == h["id"]], passages_d)
    print(f"Wrote {len(hosts_real)} real hosts, {len(passages)} passages, "
          f"{len(cases)} cases; sources tried {tried}; corpus sha256 "
          f"{C.corpus_sha256()[:16]}")


if __name__ == "__main__":
    main()
