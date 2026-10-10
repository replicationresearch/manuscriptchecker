"""Offline tests of the Plagiarism Check engine (no network)."""

import plagcheck
from plagcheck import core

ORIGINAL = ("We recruited a convenience sample of undergraduate volunteers who "
            "completed an online questionnaire about their weekend routines, "
            "favourite foods and the number of houseplants they keep at home.")
SOURCE = ("Across three preregistered studies we show that incidental exposure "
          "to green environments reliably increases subsequent prosocial "
          "behaviour, an effect that was mediated by momentary positive affect "
          "rather than by changes in perceived social norms.")
SOURCE_PDF = ("Across three preregistered studies we show that incidental expo-\n"
              "sure to green environments reliably increases subsequent proso-\n"
              "cial behaviour, an effect that was mediated by momentary posi-\n"
              "tive aﬀect rather than by changes in perceived social norms.")


def _check(rows, sources, meta=None):
    """check_document with local text files as the only sources."""
    import tempfile
    files = []
    for text in sources:
        f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False,
                                        encoding="utf-8")
        f.write(text)
        f.close()
        files.append(f.name)
    return plagcheck.check_document(
        rows, meta or {"title": "Test"},
        {"online": False, "extra_files": files, "phrase_log": False})


def _rows(*texts):
    return [{"header": "", "text": t} for t in texts]


# ---------------------------------------------------------------- normalising
def test_spelling_variants_fold_together():
    for uk, us in [("behaviour", "behavior"), ("organisation", "organization"),
                   ("analysed", "analyzed"), ("centre", "center"),
                   ("modelling", "modeling"), ("paediatric", "pediatric"),
                   ("programme", "program"), ("Müller", "muller")]:
        assert core.norm_word(uk) == core.norm_word(us), uk


def test_normaliser_leaves_ordinary_words_alone():
    for w in ("four", "hour", "your", "this", "analysis", "study", "data"):
        assert core.norm_word(w) == w


def test_pdf_artefacts_are_removed():
    assert core.tokenize_words(core.clean_text(SOURCE_PDF)) == \
        core.tokenize_words(core.clean_text(SOURCE))


def test_hyphenated_compound_split_at_line_end():
    a = core.tokenize_words(core.clean_text("a self-\nreport measure"))
    b = core.tokenize_words(core.clean_text("a self-report measure"))
    assert a == b


# ------------------------------------------------------------------- matching
def test_verbatim_paragraph_is_found():
    r = _check(_rows(ORIGINAL, SOURCE), ["Unrelated text. " * 40 + SOURCE])
    doc = r["doc"]
    assert r["sources"] and r["sources"][0]["n_runs"] == 1
    covered = r["union"]
    n_src = len(core.tokenize(SOURCE))
    assert sum(covered) == n_src
    assert not any(covered[:len(core.tokenize(ORIGINAL))])
    assert r["score"] == n_src / doc.n_scored


def test_pdf_formatted_source_still_matches():
    r = _check(_rows(ORIGINAL, SOURCE), [SOURCE_PDF])
    assert sum(r["union"]) == len(core.tokenize(SOURCE))


def test_short_overlap_is_not_reported():
    seven = " ".join(SOURCE.split()[:7])
    r = _check(_rows(ORIGINAL + " " + seven + " and then something else."),
               [SOURCE])
    assert r["score"] == 0 and r["sources"] == []
    assert len(r["compared_no_match"]) == 1     # compared, but not a "source"


def test_one_changed_word_splits_but_keeps_long_runs():
    words = SOURCE.split()
    words[16] = "substantially"
    r = _check(_rows(" ".join(words)), [SOURCE])
    assert r["sources"][0]["n_runs"] == 2


def test_quotes_and_citations_are_excluded():
    quoted = f'As they wrote, "{SOURCE}" (Smith & Jones, 2020).'
    r = _check(_rows(ORIGINAL, quoted), [SOURCE])
    assert r["score"] == 0
    assert r["doc"].quote_words >= len(core.tokenize(SOURCE)) - 1


# ------------------------------------------------------------ phrase choice
def test_every_paragraph_probed_once():
    doc = core.Doc(_rows(ORIGINAL, SOURCE, "Too short.",
                         ORIGINAL.replace("weekend", "evening") + " " + SOURCE))
    el = core.eligible_phrases(doc)
    chosen, exhausted = core.select_phrases(el, seed=1)
    assert sorted(c["row"] for c in chosen) == [0, 1, 3]
    assert exhausted == 0
    assert core.searchable_rows(doc) == [0, 1, 3]


def test_skip_used_walks_through_paragraph():
    doc = core.Doc(_rows(ORIGINAL + " " + SOURCE + " " + ORIGINAL.replace(
        "undergraduate", "postgraduate")))
    el = core.eligible_phrases(doc)
    used = set()
    for seed in range(len(el)):
        chosen, _ = core.select_phrases(el, seed, exclude=used)
        if not chosen:
            break
        assert chosen[0]["phrase"] not in used
        used.add(chosen[0]["phrase"])
    assert used == {c["phrase"] for c in el}


def test_phrase_is_surface_text_for_search_engines():
    doc = core.Doc(_rows("The participants’ self-report scores on the "
                         "behavioural inhibition questionnaire predicted later "
                         "avoidance across sessions."))
    phrases = [c["phrase"] for c in core.eligible_phrases(doc)]
    assert any("self-report" in p or "behavioural" in p for p in phrases)


def test_max_passages_caps_paragraphs():
    names = "alpha beta gamma delta epsilon zeta theta iota kappa lambda".split()
    doc = core.Doc(_rows(*[ORIGINAL.replace("houseplants", f"{n}plants")
                           .replace("questionnaire", f"{n}survey")
                           .replace("volunteers", f"{n}people")
                           .replace("routines", f"{n}routines")
                           for n in names]))
    el = core.eligible_phrases(doc)
    chosen, _ = core.select_phrases(el, seed=3, max_n=4)
    assert len(chosen) == 4


# ------------------------------------------------------ relation to manuscript
META = {"title": "Green environments increase prosocial behaviour",
        "doi": "10.1234/abc", "author_keys": [core.author_key("Müller", "Anna"),
                                              core.author_key("Smith", "J")],
        "ref_dois": {"10.9999/cited"}, "ref_blob": ""}


def test_same_doi_or_title_is_same_work():
    c = plagcheck.classify({"doi": "10.1234/abc", "title": "Other"}, META)
    assert c["same_work"]
    c = plagcheck.classify({"doi": "10.31234/osf.io/xyz", "title":
                            "Green environments increase prosocial behavior"}, META)
    assert c["same_work"]


def test_preprint_with_shared_author_and_similar_title_is_same_work():
    c = plagcheck.classify({"title": "Do green environments increase prosocial "
                            "behaviour? Three studies",
                            "author_keys": [core.author_key("Mueller", "A"),
                                            core.author_key("Muller", "A")]}, META)
    assert c["same_work"]


def test_shared_author_is_labelled_own_work():
    c = plagcheck.classify({"title": "Urban noise and attention",
                            "author_keys": [core.author_key("Muller", "Anna")]},
                           META)
    assert not c["same_work"] and c["own_work"] == ["muller"]


def test_different_initial_is_not_own_work():
    c = plagcheck.classify({"title": "Urban noise and attention",
                            "author_keys": [core.author_key("Smith", "Peter")]},
                           META)
    assert c["own_work"] == []


def test_cited_source_flag():
    c = plagcheck.classify({"title": "Something", "doi": "10.9999/cited"}, META)
    assert c["cited"] and not c["same_work"]


def test_online_flow_drops_same_work_and_keeps_phrase_only(monkeypatch):
    works = [
        {"key": "a", "source": "OpenAlex", "title": META["title"], "doi": "",
         "author_keys": [], "phrases": [{"phrase": "x"}], "text": SOURCE},
        {"key": "b", "source": "Europe PMC", "title": "Someone else's paper",
         "doi": "10.5/b", "author_keys": [], "phrases": [{"phrase": "x"}],
         "text": "Filler sentence. " * 40 + SOURCE},
        {"key": "c", "source": "OpenAlex", "title": "Paywalled paper",
         "doi": "10.5/c", "author_keys": [], "phrases": [{"phrase": "x"}],
         "text": ""},
    ]
    monkeypatch.setattr(core, "retrieve_candidates", lambda *a, **k: works)
    monkeypatch.setattr(core, "fetch_source_text", lambda s, w: w["text"])
    r = plagcheck.check_document(_rows(ORIGINAL, SOURCE), META,
                                 {"phrase_log": False, "seed": 1})
    assert [s["title"] for s in r["sources"]] == ["Someone else's paper"]
    assert [w["title"] for w in r["same_work"]] == [META["title"]]
    assert [w["title"] for w in r["phrase_only"]] == ["Paywalled paper"]
    assert r["phrase_info"]["paragraphs_probed"] == 2
    assert r["score"] > 0.4 and r["traffic_light"] == "red"
    from plagcheck.report import build_report
    html = build_report(r)
    assert "Paywalled paper" in html and "versions of this manuscript" in html


# ---------------------------------------------------------- source fetching
def test_osf_links_rewritten_to_file_download():
    for u in ("https://psyarxiv.com/6f85c/download",
              "https://osf.io/preprints/psyarxiv/6f85c/download",
              "10.31234/osf.io/6f85c", "https://osf.io/6f85c/"):
        assert core._rewrite_url(u) == "https://osf.io/download/6f85c/", u
    assert core._rewrite_url("https://example.org/a.pdf") == "https://example.org/a.pdf"


def test_bytes_to_text_detects_docx_and_html():
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml",
                   "<w:document><w:p><w:t>Hello docx</w:t></w:p></w:document>")
    assert "Hello docx" in core.bytes_to_text(buf.getvalue(), "download")
    html = b"<!doctype html><html><script>x()</script><p>Hello html</p></html>"
    t = core.bytes_to_text(html, "download")
    assert "Hello html" in t and "x()" not in t


def test_declaration_sections_are_not_searched_or_scored():
    rows = [{"header": "Results", "text": ORIGINAL},
            {"header": "Funding", "text": SOURCE},
            {"header": "Conflicts of Interest", "text": SOURCE}]
    r = _check(rows, [SOURCE])
    assert r["score"] == 0
    assert core.searchable_rows(r["doc"]) == [0]


def test_words_per_probe_adds_phrases_in_long_paragraphs():
    long_para = " ".join([ORIGINAL, SOURCE, ORIGINAL.replace("weekend", "evening"),
                          SOURCE.replace("green", "blue")])
    doc = core.Doc(_rows(long_para, ORIGINAL.replace("houseplants", "bicycles")
                         .replace("convenience", "random")))
    el = core.eligible_phrases(doc)
    one, _ = core.select_phrases(el, seed=1)
    dense, _ = core.select_phrases(el, seed=1, words_per_probe=30)
    assert len(one) == 2
    assert sum(c["row"] == 0 for c in dense) >= 3
    assert len({c["gstart"] for c in dense}) == len(dense)


def test_identical_wording_is_searched_once():
    doc = core.Doc(_rows(ORIGINAL, SOURCE, ORIGINAL))
    chosen, _ = core.select_phrases(core.eligible_phrases(doc), seed=2)
    assert len(chosen) == len({c["phrase"] for c in chosen})


def test_refused_searches_are_reported_not_hidden(monkeypatch):
    calls = {"n": 0}

    def openalex(session, phrase, mailto=None, api_key=None):
        calls["n"] += 1
        raise core.SearchFailed(quota=True)

    monkeypatch.setattr(core, "search_openalex", openalex)
    monkeypatch.setattr(core, "search_europepmc", lambda s, p: (0, []))
    r = plagcheck.check_document(
        _rows(ORIGINAL, SOURCE), {"title": "T"},
        {"phrase_log": False, "seed": 1, "backends": ("europepmc", "openalex")})
    st = r["search_stats"]["openalex"]
    assert st["ok"] == 0 and st["quota"] == r["n_phrases"]
    assert calls["n"] <= 4            # stops asking once the allowance is gone
    assert any("openalex left 2 of 2 phrase searches unanswered" in n
               for n in r["notes"])
    assert "openalex_key" not in r["options"] and "mailto" not in r["options"]


class _Resp:
    def __init__(self, status, headers):
        self.status_code, self.headers = status, headers


def test_spent_openalex_key_is_recognised():
    spent = _Resp(429, {"x-ratelimit-remaining": "1",
                        "x-ratelimit-remaining-usd": "0.0001",
                        "x-ratelimit-cost-required-usd": "0.001",
                        "retry-after": "41807"})
    burst = _Resp(429, {"retry-after": "45"})
    assert core._quota_spent(spent) and not core._quota_spent(burst)


def test_next_openalex_key_is_used_when_one_is_spent(monkeypatch):
    used = []

    def openalex(session, phrase, mailto=None, api_key=None):
        used.append(api_key)
        if api_key == "spent":
            raise core.SearchFailed(quota=True)
        return 0, []

    monkeypatch.setattr(core, "search_openalex", openalex)
    stats = {}
    core.retrieve_candidates(
        [{"phrase": f"p{i}", "row": i, "gstart": i} for i in range(5)],
        backends=("openalex",), openalex_key="spent,fresh", stats=stats, workers=1)
    assert stats["openalex"] == {"ok": 5, "failed": 0, "quota": 0, "requests": 2}
    assert used == ["spent", "fresh"]         # five phrases in one combined search


def test_openalex_combined_search_isolates_boilerplate(monkeypatch):
    """A combined search with too many results is split until the common
    phrase is alone and dropped; the rare phrase's work is kept."""
    calls = []

    def openalex(session, phrase, mailto=None, api_key=None):
        calls.append(list(phrase))
        n = (500 if "common" in phrase else 0) + (1 if "rare" in phrase else 0)
        hits = [{"key": "oa:W1", "source": "OpenAlex", "title": "Rare source",
                 "doi": "10.1/rare", "urls": [], "author_keys": [],
                 "authors": ""}] if "rare" in phrase else []
        return n, hits

    monkeypatch.setattr(core, "search_openalex", openalex)
    items = [{"phrase": p, "row": i, "gstart": i}
             for i, p in enumerate(["a", "common", "b", "rare"])]
    stats = {}
    works = core.retrieve_candidates(items, backends=("openalex",), stats=stats)
    assert [w["title"] for w in works] == ["Rare source"]
    assert stats["openalex"] == {"ok": 4, "failed": 0, "quota": 0, "requests": 5}
    assert calls[0] == ["a", "common", "b", "rare"] and len(calls) == 5


def test_openalex_batches_respect_long_phrase_rule_and_split_on_rejection(monkeypatch):
    batches = []

    def openalex(session, phrase, mailto=None, api_key=None):
        batches.append(list(phrase))
        if len(phrase) > 1 and any(p.startswith("reject") for p in phrase):
            raise core.SearchFailed(status=400)
        return 0, []

    monkeypatch.setattr(core, "search_openalex", openalex)
    long_ = ["l%d " % i + "x" * 80 for i in range(7)]
    items = [{"phrase": p, "row": i, "gstart": i}
             for i, p in enumerate(long_ + ["reject me", "short one"])]
    stats = {}
    core.retrieve_candidates(items, backends=("openalex",), stats=stats)
    assert all(sum(len(p) > core.OA_LONG for p in b) <= core.OA_MAX_LONG
               for b in batches)
    assert stats["openalex"]["ok"] == 9 and stats["openalex"]["failed"] == 0


def test_phrases_of_combined_search_are_identified(monkeypatch):
    """Works found by a combined search get their matching phrases afterwards."""
    contains = {"W1": {"p3"}, "W2": {"p0", "p7"}}
    calls = []

    def openalex(session, phrase, mailto=None, api_key=None, only=None):
        phrases = [phrase] if isinstance(phrase, str) else list(phrase)
        calls.append((len(phrases), only))
        ids = [i for i in (only or contains) if contains[i] & set(phrases)]
        return len(ids), [{"key": "oa:" + i, "openalex_id": i, "source": "OpenAlex",
                           "title": i, "doi": "", "urls": [], "author_keys": [],
                           "authors": ""} for i in ids]

    monkeypatch.setattr(core, "search_openalex", openalex)
    items = [{"phrase": f"p{i}", "row": i, "gstart": i * 10} for i in range(8)]
    stats = {}
    works = core.retrieve_candidates(items, backends=("openalex",), stats=stats)
    assert all(w["phrases"] == [] and w["batch_hits"] == 1 for w in works)
    core.resolve_batch_phrases(works, stats=stats)
    got = {w["openalex_id"]: sorted(p["phrase"] for p in w["phrases"]) for w in works}
    assert got == {"W1": ["p3"], "W2": ["p0", "p7"]}
    assert all(only for n, only in calls[1:])       # follow-ups are restricted
    assert stats["openalex"]["requests"] == len(calls) <= 1 + 14


def test_distinctive_wording_is_preferred_over_stock_phrases():
    para = ("Descriptive statistics are presented and the limitations of this "
            "study are listed as follows in the next section. Allotment holders "
            "traded rhubarb crowns, seed potatoes and gossip across the fence "
            "throughout the damp spring.")
    doc = core.Doc(_rows(para))
    for seed in range(5):
        chosen, _ = core.select_phrases(core.eligible_phrases(doc), seed)
        assert "rhubarb" in chosen[0]["phrase"] or "potatoes" in chosen[0]["phrase"]


# ------------------------------------------------- regressions from code review
def test_words_must_be_consecutive_in_the_source():
    """Two source fragments that only together cover a stretch are no match."""
    ms = "alpha beta gamma delta epsilon zeta eta theta"
    src = ("alpha beta gamma delta epsilon zeta INTERRUPTED "
           "gamma delta epsilon zeta eta theta")
    doc = core.Doc(_rows(ms))
    covered, runs = core.match_doc(doc, core.tokenize_words(src))
    assert runs == [] and not any(covered)
    covered, runs = core.match_doc(doc, core.tokenize_words("x y " + ms + " z"))
    assert runs == [(0, 8, 2)] and all(covered)


def test_run_reports_the_right_place_in_a_repetitive_source():
    ms = "one two three four five six seven eight nine ten"
    src = "one two three four five six seven " * 30 + ms
    doc = core.Doc(_rows(ms))
    _, runs = core.match_doc(doc, core.tokenize_words(src))
    assert runs[0] == (0, 10, 210)


def test_similar_title_alone_is_not_the_same_work():
    meta = dict(META, doi="", author_keys=[])
    other = plagcheck.classify(
        {"title": "Green environments do not increase prosocial behaviour",
         "doi": "10.5/other"}, meta)
    assert not other["same_work"]
    same = plagcheck.classify(
        {"title": "Green environments increase prosocial behavior"}, meta)
    assert same["same_work"]


def test_topic_words_in_a_heading_do_not_hide_a_section():
    rows = [{"header": "Ethical decision making", "text": SOURCE},
            {"header": "5. Data availability", "text": ORIGINAL}]
    r = _check(rows, [SOURCE])
    assert r["score"] > 0.9
    assert core.searchable_rows(r["doc"]) == [0]


def test_private_and_non_http_urls_are_not_downloaded():
    class NoNetwork:
        def get(self, *a, **k):
            raise AssertionError("request sent to " + str(a))
    for url in ("http://127.0.0.1:8080/x.pdf", "http://169.254.169.254/latest/",
                "http://10.0.0.5/a.pdf", "http://[::1]/a", "file:///etc/passwd",
                "ftp://example.org/a.pdf"):
        assert core._download(NoNetwork(), url) == b""


def test_redirect_to_private_address_is_refused(monkeypatch):
    class Resp:
        status_code, headers = 302, {"location": "http://127.0.0.1/secret"}

        def close(self):
            pass
    calls = []
    monkeypatch.setattr(core, "_public_url", lambda u: "127.0.0.1" not in u)
    monkeypatch.setattr(core, "_get", lambda s, u, **k: calls.append(u) or Resp())
    assert core._download(None, "https://example.org/paper.pdf") == b""
    assert calls == ["https://example.org/paper.pdf"]


def test_docx_bomb_is_not_unpacked(monkeypatch):
    import io
    import zipfile
    monkeypatch.setattr(core, "MAX_XML_BYTES", 10_000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w:p><w:t>" + "a" * 1_000_000 + "</w:t></w:p>")
    assert len(buf.getvalue()) < 5000
    assert core.docx_to_text(buf.getvalue()) == ""


def test_text_extraction_keeps_word_boundaries():
    html = "<html><p>pro<strong>social</strong> acts</p><p>Next</p><td>a</td><td>b</td></html>"
    assert core.html_to_text(html).split() == ["prosocial", "acts", "Next", "a", "b"]


def test_versioned_osf_links_and_foreign_hosts():
    assert core._rewrite_url("10.31234/osf.io/f32xq_v1") == \
        "https://osf.io/download/f32xq_v1/"
    assert core._rewrite_url("https://osf.io/preprints/psyarxiv/bc627_v2") == \
        "https://osf.io/download/bc627_v2/"
    assert core._rewrite_url("https://osf.io/abcde/?view_only=x") == \
        "https://osf.io/download/abcde/"
    foreign = "https://example.org/osf.io/abcde/"
    assert core._rewrite_url(foreign) == foreign


def test_landing_page_does_not_hide_a_later_full_text(monkeypatch):
    pages = {"https://a.example/landing": b"<html>" + b"Access blocked. " * 400 + b"</html>",
             "https://b.example/paper.docx": b"PK-docx"}
    monkeypatch.setattr(core, "_download", lambda s, u: pages[u])
    monkeypatch.setattr(core, "docx_to_text", lambda d: "real full text " * 100)
    text = core.fetch_source_text(None, {"urls": list(pages)})
    assert text.startswith("real full text")
    assert core.fetch_source_text(None, {"urls": ["https://a.example/landing"]}) == ""


def test_identical_phrases_in_one_paragraph_are_searched_once():
    sent = ("Allotment holders traded rhubarb crowns seed potatoes and gossip "
            "across the fence throughout spring. ")
    doc = core.Doc(_rows(sent * 12))
    chosen, _ = core.select_phrases(core.eligible_phrases(doc), 1,
                                    words_per_probe=30)
    assert len(chosen) == len({c["phrase"] for c in chosen})


def test_persistent_openalex_failure_is_not_retried_by_splitting(monkeypatch):
    calls = []

    def openalex(session, phrase, mailto=None, api_key=None):
        calls.append(len(phrase))
        raise core.SearchFailed(status=503)

    monkeypatch.setattr(core, "search_openalex", openalex)
    items = [{"phrase": f"p{i}", "row": i, "gstart": i} for i in range(20)]
    stats = {}
    core.retrieve_candidates(items, backends=("openalex",), stats=stats)
    assert calls == [20]
    assert stats["openalex"] == {"ok": 0, "failed": 20, "quota": 0, "requests": 1}


def test_failed_phrase_identification_is_counted_and_does_not_raise(monkeypatch):
    def first(session, phrase, mailto=None, api_key=None, only=None):
        return 1, [{"key": "oa:W1", "openalex_id": "W1", "source": "OpenAlex",
                    "title": "W1", "doi": "", "urls": [], "author_keys": [],
                    "authors": ""}]

    monkeypatch.setattr(core, "search_openalex", first)
    items = [{"phrase": f"p{i}", "row": i, "gstart": i} for i in range(4)]
    stats = {}
    works = core.retrieve_candidates(items, backends=("openalex",), stats=stats)

    def refused(session, phrase, mailto=None, api_key=None, only=None):
        raise core.SearchFailed(quota=True, status=429)

    monkeypatch.setattr(core, "search_openalex", refused)
    core.resolve_batch_phrases(works, stats=stats)
    assert works[0]["phrases"] == []
    assert stats["openalex"]["quota"] == 4 and stats["openalex"]["ok"] == 4

    def broken(session, phrase, mailto=None, api_key=None, only=None):
        raise KeyError("unexpected response")

    monkeypatch.setattr(core, "search_openalex", broken)
    stats2 = {}
    core.resolve_batch_phrases(works, stats=stats2)
    assert stats2["openalex"]["failed"] == 4


def test_openalex_key_is_sent_as_header_not_in_the_url(monkeypatch):
    seen = {}

    class Resp:
        status_code, headers = 200, {}

        def json(self):
            return {"results": [], "meta": {"count": 0}}

    def fake_get(session, url, **kw):
        seen.update(kw)
        return Resp()

    monkeypatch.setattr(core, "_get", fake_get)
    core.search_openalex(None, "some phrase", api_key="SECRET")
    assert "SECRET" not in str(seen["params"])
    assert seen["headers"] == {"Authorization": "Bearer SECRET"}


TEI = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><titleStmt>
<title level="a" type="main">A test manuscript</title></titleStmt>
<sourceDesc><biblStruct><analytic><author><persName><forename>Ann</forename>
<surname>Tester</surname></persName></author></analytic></biblStruct></sourceDesc>
</fileDesc></teiHeader><text><body>
<div><head>Introduction</head>
<p>First sentence of the first paragraph is here. Second sentence of the first
paragraph follows it. A third sentence closes the first paragraph.</p>
<p>The second paragraph starts with this sentence. It ends with this one.</p>
</div>
<div><head>Method</head><p>Only one sentence in the method paragraph.</p></div>
</body></text></TEI>"""


def test_app_path_feeds_paragraphs_not_sentences(tmp_path):
    from chetameck.paper import read_paper
    f = tmp_path / "ms.xml"
    f.write_text(TEI, encoding="utf-8")
    paper = read_paper(str(f))
    assert len(paper.table("text")) >= 6                 # one row per sentence
    rows = plagcheck._manuscript_rows(paper)
    assert [r["header"] for r in rows] == ["Introduction", "Introduction", "Method"]
    assert rows[0]["text"].startswith("First sentence") and \
        rows[0]["text"].endswith("closes the first paragraph.")
    assert rows[1]["text"].count(".") == 2


def test_unanswered_phrases_are_not_logged_as_searched(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "search_europepmc", lambda s, p: (0, []))

    def refused(session, phrase, mailto=None, api_key=None):
        raise core.SearchFailed(quota=True, status=429)

    monkeypatch.setattr(core, "search_openalex", refused)
    opts = {"phrase_log": str(tmp_path), "seed": 1,
            "backends": ("europepmc", "openalex")}
    r = plagcheck.check_document(_rows(ORIGINAL, SOURCE), {"title": "T"}, opts)
    assert r["plog"]["runs"][-1] == dict(r["plog"]["runs"][-1], complete=False,
                                         phrases=[])
    monkeypatch.setattr(core, "search_openalex", lambda *a, **k: (0, []))
    r = plagcheck.check_document(_rows(ORIGINAL, SOURCE), {"title": "T"},
                                 dict(opts, skip_used=True))
    assert r["n_phrases"] == 2 and r["plog"]["runs"][-1]["complete"]
