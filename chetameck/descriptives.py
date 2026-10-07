"""Extract descriptive statistics (mean, SD, n, ranges, percentages) from text.

The forensic metascience techniques (GRIM, GRIMMER, DEBIT, SD checks, test
recalculation, etc.) all operate on reported descriptive statistics. GROBID
text is unstructured, so this module scans sentences for common reporting
patterns and returns structured records that the forensic modules can consume.

Each record is a dict with the fields that are present:
    text_id, text, mean, sd, n, min, max, percent, label
"""

import re

import pandas as pd

from .text import text_search


# --- pattern pieces -------------------------------------------------------
NUM = r"(-?\d+(?:\.\d+)?)"

# mean: "M = 47.3", "mean = 14.5", "mean delay time of 7.00", "a mean of 0.9",
#       "with a mean delay time of 7.00"
MEAN_PAT = re.compile(
    r"(?:M|Mean|mean|MEAN|average)\s*[=:]\s*" + NUM +
    r"|(?:a\s+|the\s+)?mean\s+(?:delay time of|value of|score of|of)\s+" + NUM +
    r"|(?:a|the)\s+mean\s+" + NUM,
    re.I)

SD_PAT = re.compile(r"(?:SD|sd|S\.D\.|standard deviation)\s*[=:]\s*" + NUM,
                     re.I)

# n: "N = 17", "n= 17", "sample of 17 infants", "17 infants", "N= 17"
N_PAT = re.compile(
    r"(?:n|N)\s*[=:]\s*(\d+)"
    r"|(?:sample|group|cohort|of)\s+of\s+(\d+)"
    r"|(\d+)\s+(?:infants?|participants?|subjects?|children|adults|patients?|mice|rats?)",
    re.I)

RANGE_PAT = re.compile(
    r"(?:ranged?|range)\s+(?:from\s*)?(-?\d+(?:\.\d+)?)\s*"
    r"(?:to|–|−|[-–])\s*(-?\d+(?:\.\d+)?)", re.I)

MINMAX_PAT = re.compile(r"(?:minimum|min)\s*[=:]\s*" + NUM +
                        r"|(?:maximum|max)\s*[=:]\s*" + NUM, re.I)
PERCENT_PAT = re.compile(r"(\d+(?:\.\d+)?)\s*%", re.I)
N_PER_CENT = re.compile(r"(\d+)\s+out of\s+(\d+)", re.I)


def _search_first(pattern, text):
    m = pattern.search(str(text))
    return m


def extract_descriptives(paper):
    """Return a DataFrame of descriptive-statistic records found in the text."""
    rows = []
    for _, r in text_search(paper, "[0-9]").iterrows():
        text = str(r["text"])
        rec = {"text_id": r["text_id"], "text": text}

        m = MEAN_PAT.search(text)
        if m:
            rec["mean"] = _to_float(m.group(1))

        m = SD_PAT.search(text)
        if m:
            rec["sd"] = _to_float(m.group(1))

        m = N_PAT.search(text)
        if m:
            n = next((g for g in m.groups() if g), None)
            if n:
                rec["n"] = int(n)

        m = RANGE_PAT.search(text)
        if m:
            lo, hi = _to_float(m.group(1)), _to_float(m.group(2))
            if lo is not None and hi is not None:
                rec["min"] = min(lo, hi)
                rec["max"] = max(lo, hi)

        pct = [float(x) for x in PERCENT_PAT.findall(text)]
        if pct:
            rec["percent"] = pct

        mn = N_PER_CENT.search(text)
        if mn:
            rec["n_per_cent"] = (int(mn.group(1)), int(mn.group(2)))

        # only keep records with at least one useful statistic
        keys = set(rec.keys()) - {"text_id", "text"}
        if keys:
            rows.append(rec)

    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["text_id", "text", "mean", "sd", "n",
                                     "min", "max", "percent"])
    return df


def _to_float(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def grim(mean, n, decimals=2):
    """GRIM test: is `mean` a possible mean of `n` integer values?

    Returns (ok, possible_sum, reason).
    """
    if mean is None or not n or n <= 0:
        return None, None, "missing mean or n"
    # A mean reported to `decimals` decimal places: the true sum must be an
    # integer, and it must round to `mean` when divided by n.
    possible_sums = set()
    for candidate in range(int(round(mean * n)) - 3,
                           int(round(mean * n)) + 4):
        if candidate < 0:
            continue
        if round(candidate / n, decimals) == round(mean, decimals):
            possible_sums.add(candidate)
    if possible_sums:
        return True, min(possible_sums, key=lambda s: abs(s / n - mean)), None
    return False, None, f"{mean} is impossible with n={n}"


def grimmer(mean, sd, n):
    """GRIMMER test: does (n-1)*sd^2 + n*mean^2 equal a whole number?

    Returns (ok, target, implied, reason).
    """
    if None in (mean, sd, n) or not n or n <= 1:
        return None, None, None, "missing mean/sd/n"
    target = (n - 1) * sd ** 2 + n * mean ** 2
    nearest = round(target)
    # allow a small tolerance for rounding in the reported mean/sd
    ok = abs(target - nearest) < 0.5
    return ok, nearest, target, ("" if ok else
                                 f"sum of squares {target:.4f} is not a whole number")


def max_sd_for_range(n, minv, maxv):
    """Quick SD check: maximum possible sample SD given min/max and n.

    Exact bound is sqrt(n/(n-1)) * (max-min)/2.
    """
    if minv is None or maxv is None or not n or n <= 1:
        return None
    return (n / (n - 1)) ** 0.5 * (maxv - minv) / 2


def debit(mean, sd):
    """DEBIT check for binary (0/1) data.

    Population SD = sqrt(p(1-p)); sample SD = sqrt(n*p*(1-p)/(n-1)).
    Returns (ok, expected_sd, reason).
    """
    if mean is None or sd is None:
        return None, None, "missing mean/sd"
    if mean < 0 or mean > 1:
        return None, None, "proportion outside [0,1]"
    expected = (mean * (1 - mean)) ** 0.5
    # population form; sample form approaches this as n grows
    ok = abs(sd - expected) < 0.02 or sd <= 0.5
    return ok, expected, ("impossible SD for binary data" if sd > 0.5 else "")
