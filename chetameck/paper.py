"""Parse a GROBID TEI XML file into a Paper object.

The Paper object mirrors the schema used by the metacheck R package
(see schema/paper.json): a dict of pandas DataFrames (tables) plus a
``paper_id``. Columns match the R package so the check modules can be ported
directly.
"""

import hashlib
import html
import re
from pathlib import Path

import pandas as pd
from lxml import etree

# TEI namespace
TEI = "http://www.tei-c.org/ns/1.0"
NS = {"tei": TEI}


def _strip_ns(tag):
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _localname(node):
    return etree.QName(node).localname


def _text1(node):
    """Return the text content of a node (first element) or ''."""
    if node is None:
        return ""
    txt = "".join(node.itertext())
    return txt.strip()


def _attr(node, name, default=""):
    if node is None:
        return default
    val = node.get(name)
    return val if val is not None else default


def _find_first(node, xpath):
    return node.xpath(xpath, namespaces=NS)[0] if node.xpath(
        xpath, namespaces=NS) else None


def _find_all(node, xpath):
    return node.xpath(xpath, namespaces=NS)


def _serialize(node):
    return etree.tostring(node, encoding="unicode") if node is not None else ""


class Paper:
    """A parsed paper: paper_id + a dict of DataFrames (tables)."""

    def __init__(self, paper_id):
        self.paper_id = paper_id
        # Set by the engine when the original PDF is available (needed by
        # modules that inspect embedded images, e.g. image_forensic_check).
        self.pdf_path = None
        self.tables = {}
        # bootstrap empty tables
        for name in ("info", "author", "text", "section", "url", "bib",
                     "xref", "figure", "table", "eq", "bib_match"):
            self.tables[name] = pd.DataFrame()

    def __getitem__(self, key):
        return self.tables.get(key, pd.DataFrame())

    def table(self, name):
        return self.tables.get(name, pd.DataFrame())

    @property
    def info(self):
        return self.tables["info"]


def _parse_bib_text(ref):
    raw = ref.xpath(".//tei:note[@type='raw_reference']", namespaces=NS)
    if raw:
        parts = []
        for node in raw:
            parts.extend(node.itertext())
        return " ".join(" ".join(parts).split()).strip()
    return ""


def _parse_bib(ref, bib_id):
    """Port of R's .xml2bib()."""
    b = {"bib_type": "misc", "bib_id": bib_id, "year": None,
         "year_suffix": None, "doi": "", "title": "", "authors": "",
         "editors": "", "container": "", "volume": "", "issue": "",
         "first_page": "", "last_page": "", "publisher": "",
         "text_id": None, "bib_text": _parse_bib_text(ref)}

    doi = _find_first(ref, ".//tei:idno[@type='DOI']")
    b["doi"] = _text1(doi)
    title = _find_first(ref, ".//tei:title[@level='a']")
    b["title"] = _text1(title)
    authors = []
    for a in ref.xpath(".//tei:author//tei:persName", namespaces=NS):
        fore = " ".join(a.xpath(".//tei:forename/text()", namespaces=NS))
        surname = " ".join(a.xpath(".//tei:surname/text()", namespaces=NS))
        authors.append(f"{surname}, {fore}".strip(", "))
    b["authors"] = "; ".join(authors)
    editors = []
    for a in ref.xpath(".//tei:editor//tei:persName", namespaces=NS):
        fore = " ".join(a.xpath(".//tei:forename/text()", namespaces=NS))
        surname = " ".join(a.xpath(".//tei:surname/text()", namespaces=NS))
        editors.append(f"{surname}, {fore}".strip(", "))
    b["editors"] = "; ".join(editors)
    journal = _find_first(ref, ".//tei:title[@level='j']")
    b["journal"] = _text1(journal)
    booktitle = _find_first(ref, ".//tei:title[@level='m']")
    b["booktitle"] = _text1(booktitle)
    imprint = _find_first(ref, ".//tei:imprint")
    b["publisher"] = _text1(_find_first(imprint, ".//tei:publisher"))
    year = _text1(_find_first(imprint, ".//tei:date[@type='published']"))
    b["year"] = year
    b["year_raw"] = year
    b["volume"] = _text1(_find_first(imprint, ".//tei:biblScope[@unit='volume']"))
    b["issue"] = _text1(_find_first(imprint, ".//tei:biblScope[@unit='issue']"))
    page_scope = _find_first(imprint, ".//tei:biblScope[@unit='page']")
    if page_scope is not None:
        pages = "".join(page_scope.itertext()).strip()
        if pages == "":
            frm = page_scope.get("from")
            to = page_scope.get("to")
            if frm:
                b["first_page"] = frm
                b["last_page"] = to or frm
        else:
            b["first_page"] = pages
            b["last_page"] = pages

    # Determine bib_type / container
    if b.get("journal"):
        b["bib_type"] = "article"
        b["container"] = b["journal"]
        if not year:
            note = _find_first(ref, ".//tei:note")
            b["year_raw"] = _text1(note) or "no year"
    elif b.get("booktitle"):
        if not b.get("title"):
            b["bib_type"] = "book"
            b["title"] = b["booktitle"]
        else:
            b["bib_type"] = "incollection"
            b["container"] = b["booktitle"]

    for k in ("journal", "booktitle", "year_raw"):
        b.pop(k, None)
    return b


def _year_from_raw(raw):
    m = re.search(r"\b[12]\d{3}[a-z]?\b", raw or "")
    if not m:
        return None, None
    y = m.group(0)
    suffix = re.sub(r"\d", "", y)
    return int(re.sub(r"\D", "", y)), suffix


def parse_authors(xml):
    rows = []
    nodes = xml.xpath(".//tei:sourceDesc//tei:author[tei:persName]",
                      namespaces=NS)
    for i, a in enumerate(nodes, 1):
        given = _text1(_find_first(a, ".//tei:forename"))
        family = _text1(_find_first(a, ".//tei:surname"))
        email = _text1(_find_first(a, ".//tei:email"))
        affiliation = _text1(_find_first(a, ".//tei:affiliation"))
        orcid = _text1(_find_first(a, ".//tei:idno[@type='ORCID']"))
        rows.append({"author_id": i, "given": given, "family": family,
                     "affiliation": affiliation, "email": email,
                     "corresponding": False, "orcid": orcid, "role": []})
    return pd.DataFrame(rows)


def _clean_formatted(f):
    f = re.sub(r"^<p>|</p>$", "", f)
    f = re.sub(r"^<figDesc>|</figDesc>$", "", f)
    f = re.sub(r"\bp\.\s+(\d)", r"p$% \1", f)
    f = re.sub(r"\b([A-Z])\.", r"\1$%", f)
    return f.strip()


def _strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _split_sentences(text):
    """Split text into sentences (simple heuristic, sentence-aware)."""
    if not text:
        return []
    # Preserve ref placeholders so they aren't split wrongly
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9])", text)
    return [p.strip() for p in parts if p.strip()]


def _pull_refs(formatted):
    """Extract <ref>...</ref> spans and replace with {{ref#-#}} placeholders."""
    refs = []
    pattern = re.compile(r"<ref[^>]*>(?:(?!</ref>).)*</ref>", re.DOTALL)
    spans = list(pattern.finditer(formatted))
    # replace from last to first so positions stay valid
    out = formatted
    for i, m in enumerate(reversed(spans)):
        # assign a stable token per (index, match)
        token = f"{{{{ref{i}-{len(refs)}-x}}}}"
        out = out[:m.start()] + token + out[m.end():]
        refs.append((token, m.group(0)))
    return out, refs


def _restore_refs(text, refs):
    for token, html in refs:
        text = text.replace(token, html)
    return text


def _extract_refs_as_entities(text):
    """Parse <ref> elements into (target, type, contents) lists."""
    out = []
    try:
        parser = etree.HTMLParser(recover=True)
        root = etree.fromstring(f"<div>{text}</div>", parser)
        for ref in root.xpath(".//ref"):
            target = ref.get("target") or ""
            rtype = ref.get("type") or ""
            contents = "".join(ref.itertext())
            out.append((target, rtype, contents.strip()))
    except Exception:  # noqa: BLE001
        pass
    return out


def parse_text(xml):
    """Port of .tei_text() + .process_full_text().

    Returns (text_df, section_df). Each row of text_df is a sentence.
    """
    abstract_ps = xml.xpath(".//tei:abstract//tei:p", namespaces=NS)
    rows = []
    if abstract_ps:
        for p in abstract_ps:
            rows.append({"header": "Abstract",
                         "formatted": _serialize(p),
                         "div": 0, "section": "abstract"})

    divs = xml.xpath(".//tei:text//tei:body//tei:div", namespaces=NS)
    for i, div in enumerate(divs, 1):
        h = _find_first(div, ".//tei:head")
        header = _serialize(h) if h is not None else f"[div-{i:02d}]"
        ps = div.xpath(".//tei:p", namespaces=NS)
        if not ps:
            ps = [div]
        for p in ps:
            rows.append({"header": header, "formatted": _serialize(p),
                         "div": i, "section": None})

    back_divs = xml.xpath(".//tei:back//tei:div", namespaces=NS)
    for div in back_divs:
        t = div.get("type") or ""
        if t == "references" or not t:
            continue
        h = _find_first(div, ".//tei:head")
        header = _serialize(h) if h is not None else ""
        for p in div.xpath(".//tei:p", namespaces=NS):
            rows.append({"header": header, "formatted": _serialize(p),
                         "div": None, "section": t})

    for fig in xml.xpath(".//tei:figure", namespaces=NS):
        figid = fig.get("id") or ""
        fd = _find_first(fig, ".//tei:figDesc")
        h = _find_first(fig, ".//tei:head")
        section = re.sub(r"_\d+$", "", figid)
        div = None
        m = re.match(r"^(?:fig|tab)_(\d+)$", figid)
        if m:
            div = int(m.group(1))
        rows.append({"header": _serialize(h) if h is not None else "",
                     "formatted": _serialize(fd) if fd is not None else "",
                     "div": div, "section": section})

    for note in xml.xpath(".//tei:note[@place='foot']", namespaces=NS):
        noteid = note.get("id") or ""
        rows.append({"header": "", "formatted": _serialize(note),
                     "div": None,
                     "section": re.sub(r"_\d+$", "", noteid)})

    df = pd.DataFrame(rows)
    if df.empty:
        empty = pd.DataFrame(columns=["header", "formatted", "div", "section"])
        return empty, pd.DataFrame(columns=[
            "section_id", "header", "parent_section_id", "section_type",
            "classification_score"])

    df = df[df["formatted"].fillna("").astype(str) != ""].copy()
    # renumber paragraphs
    df = df.reset_index(drop=True)

    sentences = []
    for p_idx, (_, r) in enumerate(df.iterrows()):
        fmt = _clean_formatted(str(r["formatted"]))
        cleaned, refs = _pull_refs(fmt)
        for s in _split_sentences(cleaned):
            s = _restore_refs(s, refs)
            # strip html to plain text
            plain = _strip_tags(s)
            sentences.append({
                "header": r["header"], "formatted": s, "section": r["section"],
                "div": r["div"], "text": plain, "tei_paragraph": p_idx})

    st = pd.DataFrame(sentences)
    if st.empty:
        empty = pd.DataFrame(columns=[
            "text", "text_id", "paragraph_id", "section_id", "page_number",
            "header", "section_type", "formatted"])
        return empty, pd.DataFrame(columns=[
            "section_id", "header", "parent_section_id", "section_type",
            "classification_score"])

    # classify section types by header
    def classify(header, section):
        ns_ = re.sub(r"\s", "", str(header or ""))
        if section:
            return section
        if re.search(r"abstract", ns_, re.I):
            return "abstract"
        if re.search(r"intro", ns_, re.I):
            return "intro"
        if re.search(r"method|material", ns_, re.I):
            return "method"
        if re.search(r"result", ns_, re.I):
            return "results"
        if re.search(r"discuss", ns_, re.I):
            return "discussion"
        if re.search(r"bibliograph|reference", ns_, re.I):
            return "references"
        return None

    st["section_type"] = [classify(h, s) for h, s in zip(st["header"], st["section"])]
    # fill forward section type for blanks
    prev = None
    filled = []
    for stype in st["section_type"]:
        if stype is None:
            stype = prev
        else:
            prev = stype
        filled.append(stype)
    st["section_type"] = filled

    st = st.reset_index(drop=True)
    st["paragraph_id"] = range(1, len(st) + 1)
    st["text_id"] = range(1, len(st) + 1)
    st["page_number"] = None

    # build section table
    sec = (st.groupby(["div", "header", "section_type"])
             .agg(sec_id=("text_id", "first"))
             .reset_index())
    # section_id must be a proper int
    sec = sec.reset_index(drop=True)
    sec["section_id"] = range(len(sec))
    # map back to sentences
    div_map = {}
    for _, srow in sec.iterrows():
        key = (srow["div"], srow["header"])
        div_map[key] = srow["section_id"]
    st["section_id"] = [div_map.get((d, h), 0)
                        for d, h in zip(st["div"], st["header"])]

    # tei_paragraph: index of the TEI paragraph a sentence came from
    # (paragraph_id numbers the sentences themselves)
    text_df = st[["text", "text_id", "paragraph_id", "tei_paragraph", "section_id",
                  "page_number", "header", "section_type", "formatted"]].copy()

    section_df = pd.DataFrame({
        "section_id": sec["section_id"],
        "header": sec["header"],
        "parent_section_id": [None] * len(sec),
        "section_type": sec["section_type"],
        "classification_score": [None] * len(sec),
    })

    # drop sentence header/section_type (they live in section table)
    text_df = text_df.drop(columns=["header", "section_type"])
    return text_df, section_df


def parse_bib(xml):
    refs = xml.xpath(".//tei:listBibl//tei:biblStruct", namespaces=NS)
    if not refs:
        return pd.DataFrame()
    rows = []
    for i, ref in enumerate(refs, 1):
        b = _parse_bib(ref, i)
        rows.append(b)
    bib = pd.DataFrame(rows)
    if bib.empty:
        return bib
    years = []
    suffixes = []
    for raw in bib.get("year", ""):
        y, sfx = _year_from_raw(raw)
        years.append(y)
        suffixes.append(sfx)
    bib["year"] = years
    bib["year_suffix"] = suffixes
    return bib


def parse_xrefs(text_df):
    """Extract <ref> cross-references from the formatted text."""
    null_tbl = pd.DataFrame(columns=["xref_id", "xref_type", "contents",
                                     "text_id"])
    rows = []
    for _, r in text_df.iterrows():
        fmt = r.get("formatted")
        if not fmt or pd.isna(fmt):
            continue
        for target, rtype, contents in _extract_refs_as_entities(str(fmt)):
            if rtype == "url":
                continue
            xid = re.sub(r"\D", "", target or "")
            rows.append({"xref_id": int(xid) if xid else None,
                         "xref_type": rtype, "contents": contents,
                         "text_id": r["text_id"]})
    if not rows:
        return null_tbl
    return pd.DataFrame(rows)


def parse_urls(text_df):
    null_tbl = pd.DataFrame(columns=["href", "link_text", "text_id"])
    rows = []
    for _, r in text_df.iterrows():
        fmt = r.get("formatted")
        if not fmt or pd.isna(fmt):
            continue
        for target, rtype, contents in _extract_refs_as_entities(str(fmt)):
            if rtype == "url":
                href = (target or "").strip()
                href = href.rstrip(".")
                rows.append({"href": href, "link_text": contents,
                             "text_id": r["text_id"]})
    if not rows:
        return null_tbl
    return pd.DataFrame(rows)


def read_paper(xml_path):
    """Parse a GROBID TEI XML file into a Paper object."""
    xml_path = Path(xml_path)
    tree = etree.parse(str(xml_path))
    xml = tree.getroot()

    paper_id = xml_path.stem
    paper = Paper(paper_id)

    title = _text1(_find_first(xml, ".//tei:titleStmt/tei:title"))
    keywords = [_text1(k) for k in xml.xpath(".//tei:textClass//tei:keywords//tei:term",
                                             namespaces=NS)]
    keywords = [k for k in keywords if k]
    doi = _text1(_find_first(xml, ".//tei:idno[@type='DOI']"))
    file_hash = hashlib.md5(xml_path.read_bytes()).hexdigest()[:16]
    grobid = _find_first(xml, ".//tei:application[@ident='GROBID']")
    gv = grobid.get("version") if grobid is not None else None
    input_format = f"grobid {gv}" if gv else "Unknown TEI XML"

    paper.tables["info"] = pd.DataFrame([{
        "title": title, "keywords": [keywords], "doi": doi,
        "file_hash": file_hash, "input_format": input_format,
        "file_name": str(xml_path), "bibr_version": "10.0",
        "paper_type": "unknown", "paper_type_confidence": 0,
        "oecd_l1": None, "oecd_l2": None, "oecd_confidence": None}])

    paper.tables["author"] = parse_authors(xml)
    text_df, section_df = parse_text(xml)
    paper.tables["text"] = text_df
    paper.tables["section"] = section_df

    # add synthetic References section + text for bib entries
    bib = parse_bib(xml)
    if not bib.empty:
        max_sec = int(section_df["section_id"].max()) + 1 if not section_df.empty else 1
        max_text = int(text_df["text_id"].max()) if not text_df.empty else 0
        max_para = int(text_df["paragraph_id"].max()) if not text_df.empty else 0
        ref_sec = pd.DataFrame([{
            "section_id": max_sec, "header": "References",
            "parent_section_id": None, "section_type": "references",
            "classification_score": None}])
        section_df = pd.concat([section_df, ref_sec], ignore_index=True)

        text_ids = list(range(max_text + 1, max_text + 1 + len(bib)))
        para_ids = list(range(max_para + 1, max_para + 1 + len(bib)))
        ref_rows = []
        for tid, pid, bt in zip(text_ids, para_ids, bib["bib_text"]):
            ref_rows.append({"text": bt, "text_id": tid,
                             "paragraph_id": pid, "section_id": max_sec,
                             "page_number": None})
        ref_text = pd.DataFrame(ref_rows)
        text_df = pd.concat([text_df, ref_text], ignore_index=True)
        bib["text_id"] = text_ids
        paper.tables["text"] = text_df
        paper.tables["section"] = section_df
    if "bib_text" in bib.columns:
        bib = bib.drop(columns=["bib_text"])
    paper.tables["bib"] = bib

    paper.tables["xref"] = parse_xrefs(text_df)
    paper.tables["url"] = parse_urls(text_df)

    # figures / tables
    fig_secs = section_df[section_df["section_type"] == "figure"]["section_id"].tolist()
    paper.tables["figure"] = pd.DataFrame({
        "figure_id": range(1, len(fig_secs) + 1),
        "section_id": fig_secs,
        "image": [None] * len(fig_secs),
        "page_number": [None] * len(fig_secs),
    })
    tab_secs = section_df[section_df["section_type"] == "table"]["section_id"].tolist()
    paper.tables["table"] = pd.DataFrame({
        "table_id": range(1, len(tab_secs) + 1),
        "section_id": tab_secs,
        "html": [None] * len(tab_secs),
        "contents": [None] * len(tab_secs),
        "page_number": [None] * len(tab_secs),
    })

    # equations
    from .text import extract_eq
    eq = extract_eq(paper)
    paper.tables["eq"] = eq

    # bib_match empty (no external service enrichment in ChetaMeck by default)
    paper.tables["bib_match"] = pd.DataFrame(columns=[
        "service", "bib_id", "service_id", "score", "bib_type", "doi",
        "title", "authors", "editors", "publisher", "year", "date",
        "container", "volume", "issue", "first_page", "last_page",
        "edition", "version", "url"])

    return paper
