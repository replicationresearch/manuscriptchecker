"""Text search and extraction helpers, ported from the metacheck R package.

These operate on a :class:`~chetameck.paper.Paper` object and mirror the R
functions ``text_search``, ``text_expand``, ``extract_p_values``,
``extract_eq`` and ``extract_urls``.
"""

import re

import pandas as pd

# Operators used when matching p-values / equations. Note the unicode symbols
# mirror those used by the R package (≈, ≠, ≤, ≥, ≪, ≫, ~, etc.).
OPERATORS = ["=", "<", ">", "~", "≈", "≠", "≤", "≥", "≪", "≫"]
OP_CHARS = re.escape("".join(OPERATORS))

P_VALUE_PATTERN = (
    r"\bp-?(value)?\s*"                      # p / p-value
    r"[" + OP_CHARS + r"]{1,2}\s*"           # comparator(s)
    r"(n\.?s\.?|\d?\.\d+)"                   # value or n.s.
    r"\s*(e\s*-\d+)?"                        # scientific notation e-xx
    r"(\s*[x\*]\s*10\s*\^\s*-\d+)?"          # scientific notation x10^-xx
)


def _text_table(paper, include_refs=False):
    text = paper.table("text").copy()
    sections = paper.table("section")
    if not text.empty and not sections.empty:
        text = text.merge(
            sections[["section_id", "header", "section_type"]],
            on="section_id", how="left")
    for col in ("text", "text_id", "section_id", "paragraph_id", "paper_id",
                "header", "section_type"):
        if col not in text.columns:
            text[col] = None
    text["paper_id"] = paper.paper_id
    if not include_refs and "section_type" in text.columns:
        text = text[text["section_type"].fillna("") != "references"]
    text = text.reset_index(drop=True)
    return text


def text_search(paper, pattern=".*", return_type="sentence", ignore_case=True,
                fixed=False, perl=True, exclude=False, search_header=False,
                include_refs=False):
    """Search the paper text and return matched rows.

    ``return_type`` may be one of: sentence, paragraph, section, header,
    match, paper_id.
    """
    if isinstance(pattern, (list, tuple)):
        frames = []
        for p in pattern:
            frames.append(text_search(paper, p, return_type, ignore_case,
                                      fixed, perl, exclude, search_header,
                                      include_refs))
        if exclude:
            if frames:
                out = frames[0]
                for fr in frames[1:]:
                    out = pd.merge(out, fr, how="inner")
                return out
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True)
        return out.drop_duplicates().reset_index(drop=True)

    text = _text_table(paper, include_refs=include_refs)
    if text.empty:
        return text

    flags = re.I if ignore_case else 0
    try:
        if fixed:
            mask = [pattern in str(x) for x in text["text"]]
        else:
            mask = [bool(re.search(pattern, str(x), flags)) for x in text["text"]]
    except re.error as e:  # noqa: BLE001
        raise ValueError(f"Check the pattern argument: {e}") from e

    mask = pd.Series(mask, index=text.index)
    if search_header and "header" in text.columns:
        hmask = pd.Series([bool(re.search(pattern, str(h), flags))
                           for h in text["header"]], index=text.index)
        mask = mask | hmask
    if exclude:
        mask = ~mask

    ft = text[mask].reset_index(drop=True)

    if return_type == "sentence":
        out = ft
    elif return_type == "match":
        out_rows = []
        for _, r in ft.iterrows():
            for m in re.finditer(pattern, str(r["text"]), flags):
                row = r.copy()
                row["text"] = m.group(0)
                out_rows.append(row)
        out = pd.DataFrame(out_rows) if out_rows else ft.iloc[0:0]
    elif return_type == "paper_id":
        if "paper_id" in ft.columns:
            out = ft[["paper_id"]].drop_duplicates()
        else:
            out = pd.DataFrame({"paper_id": [paper.paper_id]})
    else:
        # paragraph / section / header
        groups = {"paragraph": ["section_type", "header", "section_id",
                                "paragraph_id", "paper_id"],
                  "section": ["section_type", "section_id", "paper_id"],
                  "header": ["section_type", "header", "section_id",
                             "paper_id"]}.get(return_type)
        if groups is None:
            groups = ["section_type", "header", "section_id",
                      "paragraph_id", "paper_id"]
        groups = [g for g in groups if g in ft.columns]
        # for paragraph return, join matched sentences per paragraph
        if return_type == "paragraph" and "paragraph_id" in ft.columns:
            out = ft.groupby(groups, dropna=False).agg(
                text=("text", lambda s: " ".join(s.astype(str))),
                **{"text_id": ("text_id", "first")}
            ).reset_index()
        elif return_type == "section" and "section_id" in ft.columns:
            out = ft.groupby(groups, dropna=False).agg(
                text=("text", lambda s: "\n\n".join(s.astype(str)))
            ).reset_index()
        else:
            out = ft.groupby(groups, dropna=False).agg(
                text=("text", lambda s: " ".join(s.astype(str)))
            ).reset_index()
        out["text"] = out["text"].str.replace(r"\s+", " ", regex=True)
    out = out.drop_duplicates().reset_index(drop=True)
    return out


def text_expand(results_table, paper, expand_to="sentence", plus=0, minus=0):
    """Join a results table back to the paper text to add an ``expanded`` col."""
    by = ["paper_id", "section_id", "paragraph_id", "text_id", "text"]
    ft = text_search(paper)
    if ft.empty:
        results_table = results_table.copy()
        results_table["expanded"] = results_table.get("text", "")
        return results_table
    cols = [c for c in by if c in ft.columns]
    ft = ft[cols]

    if expand_to == "sentence":
        groupby_cols = [c for c in ("paper_id", "section_id", "paragraph_id",
                                    "text_id") if c in ft.columns]
        agg = ft.groupby(groupby_cols, dropna=False).agg(
            expanded=("text", lambda s: " ".join(s.astype(str)))
        ).reset_index()
    elif expand_to in ("paragraph", "section"):
        groupby_cols = [c for c in ("paper_id", "section_id", "paragraph_id")
                        if c in ft.columns]
        agg = ft.groupby(groupby_cols, dropna=False).agg(
            expanded=("text", lambda s: " ".join(s.astype(str)))
        ).reset_index()
    else:
        agg = ft.copy()
        agg["expanded"] = agg["text"]

    join_cols = [c for c in groupby_cols if c in results_table.columns]
    if not join_cols and "text" in results_table.columns and "text" in agg.columns:
        merged = results_table.copy()
        text_map = dict(zip(agg["text"], agg["expanded"]))
        merged["expanded"] = merged["text"].map(lambda t: text_map.get(t, t))
        return merged
    # coerce join columns to a common type (paper_id etc. may be object vs float)
    for c in join_cols:
        if c in results_table.columns and c in agg.columns:
            results_table[c] = results_table[c].astype(str)
            agg[c] = agg[c].astype(str)
    merged = results_table.merge(agg, on=join_cols, how="left")
    merged["expanded"] = merged["expanded"].fillna(merged["text"])
    return merged


def extract_p_values(paper):
    """Find p-value statements in the text.

    Returns a DataFrame with ``text`` (the matched string, e.g. ``p = 0.04``),
    ``p_comp`` (comparator) and ``p_value`` (float or None).
    """
    p = text_search(paper, P_VALUE_PATTERN, return_type="match",
                    ignore_case=False)
    if p.empty:
        return p
    p = p.copy()
    comp_pat = re.compile(r"[" + OP_CHARS + r"]{1,2}")
    p["p_comp"] = p["text"].apply(lambda t: (comp_pat.search(t) or re.match("", t)).group(0))
    p["p_value"] = p["text"].apply(_parse_pvalue)
    return p


def _parse_pvalue(text):
    m = re.search(r"[" + OP_CHARS + r"]{1,2}\s*"
                  r"(n\.?s\.?|\d?\.\d+)\s*(e\s*-\d+)?"
                  r"(\s*[x\*]\s*10\s*\^\s*-\d+)?", text)
    if not m:
        return None
    val = m.group(1)
    if val and re.fullmatch(r"n\.?\s*s\.?", val or "", re.I):
        return None
    num = m.group(2)
    if num is None:
        num = m.group(3)
    s = re.sub(r"\s", "", val or "")
    if num:
        s += num.replace(" ", "")
    s = s.replace("x*10^", "e").replace("*10^", "e")
    s = s.replace("x10^", "e")
    try:
        return float(s)
    except ValueError:
        return None


def extract_urls(paper):
    # Require a scheme or a recognisable TLD to avoid false positives such as
    # "werecomplete.Ofthe" being matched as a bare domain.
    pattern = (r"\b((?:https?://|ftp://)[^\s<>\"']+"
               r"|(?:www\.)[\w.-]+\.[a-z]{2,}(?:/\S*)?"
               r"|[\w.-]+\.(?:com|org|net|edu|gov|io|de|uk|info|biz|ru|cn|"
               r"edu|xyz|app|dev|link|online|site|edu)\b)"
               r"(?=[\s.,;:)\]}<!\"']|$)")
    return text_search(paper, pattern, return_type="match", perl=True)


GREEK = {"beta": "β", "eta": "η", "alpha": "α", "delta": "δ", "Delta": "Δ",
         "chi": "χ", "mu": "μ", "sigma": "σ", "rho": "ρ", "theta": "Θ",
         "lambda": "λ", "gamma": "γ", "tau": "τ", "pi": "π"}


def extract_eq(paper):
    """Find equations of the form ``LHS (df) comp RHS`` in the text.

    Returns a DataFrame with columns text_id, grp_id, lhs, df, comp, rhs.
    """
    # Characters allowed in the "LHS" of an equation (the test-statistic
    # name): Latin letters, the Greek symbols used for effect sizes (beta,
    # eta, chi, ...), superscript-2 (R-squared), plus punctuation used in
    # statistic notation. The previous version of this character class
    # contained corrupted/mis-encoded characters and an invalid range, which
    # made the regex fail to compile at all.
    gr = ''.join(GREEK.values()) + chr(0x00b2) + r"a-zA-Z\-_.0-9{}\^\\"
    op = OP_CHARS
    pattern = (r"(?:(?:Hedge.{0,3}|Cronbach.{0,2}|Cohen.{0,2}|\d{1,2}%)\s+)?"
               r"[" + gr + r"]+\s*"
               r"(?:\([^)]*\))?\s*"
               r"[" + op + r"]{1,3}\s*"
               r"([0-9\.,+-]*[0-9]|\[[^\]]+\]|n\.?\s*s\.?)"
               r"\s*(e\s*-\d+)?"
               r"(\s*[x\*]\s*10\s*\^\s*-\d+)?")

    # Search for sentences containing an operator. This must be a character
    # class ("[=<>...]", any one of them), not the operators concatenated
    # into one literal string - the latter only matches a sentence that
    # contains all ten operator characters back-to-back in that exact order,
    # which effectively never happens, silently making this function (and
    # everything built on it, e.g. df_consistency_check) return nothing.
    base = text_search(paper, "[" + OP_CHARS + "]")
    if base.empty:
        return pd.DataFrame(columns=["text_id", "grp_id", "lhs", "df", "comp",
                                     "rhs"])
    # `base` is already the (DataFrame) search result above, not a Paper -
    # match the equation pattern directly against its rows (this mirrors
    # text_search's own return_type="match" branch) rather than recursing
    # into text_search with a DataFrame where it expects a Paper.
    match_rows = []
    for _, r in base.iterrows():
        for m in re.finditer(pattern, str(r["text"]), re.I):
            row = r.copy()
            row["text"] = m.group(0)
            match_rows.append(row)
    eq = pd.DataFrame(match_rows) if match_rows else base.iloc[0:0]
    if eq.empty:
        return pd.DataFrame(columns=["text_id", "grp_id", "lhs", "df", "comp",
                                     "rhs"])

    eq = eq.copy()
    # `eq` is built from only the rows that matched the pattern, so its index
    # has gaps (e.g. 0,1,2,4,...). Reset it so the positional loops below that
    # use `eq.loc[i, ...]` with an integer i actually resolve. The later
    # reset_index(drop=True) would otherwise come too late (after the first
    # .loc access) and raise KeyError.
    eq = eq.reset_index(drop=True)
    # extract df
    df_pat = re.compile(r"\([^)]*\)")
    dfs = []
    for t in eq["text"]:
        m = df_pat.search(str(t))
        if m:
            dfs.append(m.group(0))
        else:
            dfs.append(None)
    eq["df"] = dfs
    for i, d in enumerate(dfs):
        if d:
            eq.loc[i, "text"] = re.sub(r"\s+", " ",
                                       str(eq.loc[i, "text"]).replace(d, "", 1))

    comp_pat = re.compile(r"[" + op + r"]{1,2}")
    comps = []
    for t in eq["text"]:
        m = comp_pat.search(str(t))
        comps.append(m.group(0) if m else "")
    eq["comp"] = comps
    sides = []
    for t in eq["text"]:
        parts = re.split(r"\s*[" + op + r"]{1,2}\s*", str(t))
        sides.append((parts[0].strip() if parts else "",
                      parts[1].strip() if len(parts) > 1 else ""))
    eq["lhs"] = [s[0] for s in sides]
    eq["rhs"] = [s[1] for s in sides]

    eq = eq.reset_index(drop=True)
    eq["grp_id"] = 1
    for i in range(1, len(eq)):
        if eq.loc[i, "text_id"] != eq.loc[i - 1, "text_id"]:
            eq.loc[i, "grp_id"] = eq.loc[i - 1, "grp_id"] + 1
        else:
            eq.loc[i, "grp_id"] = eq.loc[i - 1, "grp_id"]

    eq = eq[~eq["lhs"].astype(str).str.fullmatch(r"[0-9]")]
    cols = ["text_id", "grp_id", "lhs", "df", "comp", "rhs"]
    eq = eq[cols].sort_values(["text_id", "grp_id"]).reset_index(drop=True)
    return eq
