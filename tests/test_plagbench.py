"""Offline tests of the benchmark tooling in scripts/plagbench (no network)."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "plagbench"))
import corpus as C  # noqa: E402
import pan  # noqa: E402


# ------------------------------------------------------------ PAN measures
def test_pan_perfect_detection():
    case = (100, 200, 500, 600)
    m = pan.pan_measures([([case], [case])])
    assert m["precision"] == m["recall"] == m["granularity"] == m["plagdet"] == 1.0


def test_pan_half_recall_full_precision():
    # detection covers the first half of the case in both documents
    m = pan.pan_measures([([(100, 200, 500, 600)], [(100, 150, 500, 550)])])
    assert m["recall"] == pytest.approx(0.5)
    assert m["precision"] == pytest.approx(1.0)
    assert m["plagdet"] == pytest.approx(2 * 0.5 / 1.5)        # F1, granularity 1


def test_pan_overlong_detection_halves_precision():
    # detection twice as long as the case on both sides
    m = pan.pan_measures([([(100, 200, 500, 600)], [(100, 300, 500, 700)])])
    assert m["recall"] == pytest.approx(1.0)
    assert m["precision"] == pytest.approx(0.5)


def test_pan_split_detection_is_penalised_by_granularity():
    import math
    dets = [(100, 150, 500, 550), (150, 200, 550, 600)]
    m = pan.pan_measures([([(100, 200, 500, 600)], dets)])
    assert m["recall"] == m["precision"] == 1.0
    assert m["granularity"] == 2.0
    assert m["plagdet"] == pytest.approx(1 / math.log2(3))


def test_pan_detection_in_wrong_source_place_does_not_count():
    # right place in the suspicious document, wrong place in the source
    m = pan.pan_measures([([(100, 200, 500, 600)], [(100, 200, 900, 1000)])])
    assert m["recall"] == 0 and m["precision"] == 0


def test_pan_false_detection_in_negative_pair_lowers_precision():
    case = (100, 200, 500, 600)
    m = pan.pan_measures([([case], [case]), ([], [(0, 50, 0, 50)])])
    assert m["recall"] == 1.0 and m["precision"] == pytest.approx(0.5)


# ------------------------------------------------------------ corpus assembly
HOST = {"id": "h", "rows": [
    {"header": "Intro", "text": "First sentence here. Second sentence here."},
    {"header": "Intro", "text": "Alpha one. Beta two. Gamma three."},
    {"header": "Method", "text": "Only paragraph."}]}
PASSAGES = {"p1": {"text": "NEW PARAGRAPH TEXT."}, "p2": {"text": "INSERTED SENTENCE."}}


def test_assemble_inserts_paragraph_and_sentence():
    cases = [{"case_id": "h:p1", "host": "h", "passage": "p1", "type": "paragraph",
              "row": 2, "cut": None},
             {"case_id": "h:p2", "host": "h", "passage": "p2",
              "type": "sentence_in_para", "row": 1, "cut": 10}]
    rows, spans = C.assemble(HOST, cases, PASSAGES)
    assert [r["text"] for r in rows] == [
        "First sentence here. Second sentence here.",
        "Alpha one. INSERTED SENTENCE. Beta two. Gamma three.",
        "NEW PARAGRAPH TEXT.", "Only paragraph."]
    for cid, (row, a, b) in spans.items():
        assert rows[row]["text"][a:b] == PASSAGES[cid.split(":")[1]]["text"]
    assert rows[2]["header"] == "Method"
    assert HOST["rows"][1]["text"] == "Alpha one. Beta two. Gamma three."   # untouched


def test_assemble_without_cases_returns_host_unchanged():
    rows, spans = C.assemble(HOST, [], PASSAGES)
    assert rows == HOST["rows"] and spans == {}


def test_committed_corpus_is_consistent():
    """Every case of the committed corpus assembles; licences are permissive."""
    if not (C.CORPUS / "recipe.json").exists():
        pytest.skip("corpus not built")
    hosts, passages, recipe = C.load()
    assert len({c["case_id"] for c in recipe["cases"]}) == len(recipe["cases"])
    assert len({c["passage"] for c in recipe["cases"]}) == len(recipe["cases"])
    for h in hosts.values():
        C.assemble(h, [c for c in recipe["cases"] if c["host"] == h["id"]], passages)
        assert h["license"].startswith(("CC BY", "CC0")), h["id"]
    for p in passages.values():
        src = p["source"]
        assert re.fullmatch(r"CC BY(-SA)? \d\.\d|CC0 1\.0", src["license"]), p["id"]
        assert src["license"].split()[1].lower() in src["license_url"] or \
            src["license"].startswith("CC0"), p["id"]
        assert src["license_url"] and src["creators"] and src["url"], p["id"]


def test_real_hosts_keep_text_after_citation_markers():
    """Regression: paragraphs must not stop at a citation marker."""
    if not (C.CORPUS / "recipe.json").exists():
        pytest.skip("corpus not built")
    hosts, _, _ = C.load()
    for h in hosts.values():
        cut = [r["text"][-30:] for r in h["rows"] if r["text"].rstrip().endswith(("[", "("))]
        assert not cut, (h["id"], cut[:2])


def test_pan_offset_map_matches_engine_cleaning():
    from plagcheck import core
    text = "cafe\u0301 de-\nsign ﬁrst na\u00efve co\u00adoperate"
    clean, mp = pan.clean_with_map(text)
    assert clean == core.clean_text(text)
    assert len(mp) == len(clean) + 1 and mp[-1] == len(text)


# ------------------------------------------------------------ licence parsing
def test_licence_parsing_is_strict():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import build_corpus as B
    by4 = ("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/")
    assert B.parse_cc('<license xlink:href="https://creativecommons.org/licenses/by/4.0/">') == by4
    assert B.parse_cc("under a Creative Commons Attribution 4.0 International License") == by4
    assert B.parse_cc("Creative Commons Attribution-ShareAlike 3.0 licence") == \
        ("CC BY-SA 3.0", "https://creativecommons.org/licenses/by-sa/3.0/")
    assert B.parse_cc("https://creativecommons.org/publicdomain/zero/1.0/")[0] == "CC0 1.0"
    assert B.parse_cc("Creative Commons Attribution License (CC BY)") is None      # no version
    assert B.parse_cc("Creative Commons Attribution-NonCommercial 4.0") is None
    assert B.parse_cc("http://creativecommons.org/licenses/by-nc-nd/4.0/") is None
    assert B.parse_cc("All rights reserved.") is None
