"""Effect-size and confidence-interval consistency checks.

Python port of the core of ``escicheck`` (EffectCheck): for statistical results
that report both a test statistic and an effect size, verify that the reported
effect size is consistent with what the test statistic implies (type-matched:
d vs d, eta^2 vs eta^2, etc.). Also verifies that a reported confidence
interval is internally consistent with the point estimate.

Only the common effect-size types are covered (the validated core):
  * d / g / dz from t-tests
  * r from t-tests
  * eta^2 / partial eta^2 / omega^2 / Cohen's f from F-tests
  * phi / Cramer's V from chi-square tests

CI consistency uses:
  * normal-approximation for independent d
  * Fisher-z for r
  * noncentral-F inversion for eta^2
  * noncentral-t inversion for dz

See https://github.com/giladfeldman/escicheck (MIT) for the reference design.
"""

import re

import numpy as np
import pandas as pd
from scipy import stats

from .registry import register, module_output, md_table
from ..text import text_search

# --- pattern library ---------------------------------------------------------

# a number that may be written without a leading digit (e.g. ".34", "-.5")
NUM = r"[+-]?(?:\d+\.?\d*|\.\d+)"

T_PATTERN = re.compile(r"t\s*\(\s*(\d+)\s*\)\s*=\s*(" + NUM + ")", re.I)
F_PATTERN = re.compile(r"F\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)\s*=\s*(" + NUM + ")", re.I)
CHISQ_PATTERN = re.compile(
    r"(?:\u03c7|chi(?:-squared)?|chisq)\s*[2\u00b2]?\s*\(\s*(\d+)\s*\)\s*=\s*(" + NUM + ")",
    re.I)

# Effect-size tokens: (regex, type)
ES_TOKENS = [
    (re.compile(r"(?i)\b(?:cohen(?:'s)?\s*d|d)\s*=\s*(" + NUM + ")"), "d"),
    (re.compile(r"(?i)\b(?:hedges(?:'s)?\s*g|g)\s*=\s*(" + NUM + ")"), "g"),
    (re.compile(r"(?i)\b(?:dz|d\s*z)\s*=\s*(" + NUM + ")"), "dz"),
    (re.compile(r"(?i)\b(?:r|pearson(?:'s)?\s*r)\s*=\s*(" + NUM + ")"), "r"),
    (re.compile(r"(?i)\b(?:partial\s*)?\u03b7p?\s*[2\u00b2]?\s*=\s*(" + NUM + ")"), "eta2"),
    (re.compile(r"(?i)\b(?:partial\s*)?eta(?:-|_)?squared\s*=\s*(" + NUM + ")"), "eta2"),
    (re.compile(r"(?i)\b(?:partial\s*)?eta\s*[2\u00b2]?\s*=\s*(" + NUM + ")"), "eta2"),
    (re.compile(r"(?i)\b(?:partial\s*)?\u03c9\s*[2\u00b2]?\s*=\s*(" + NUM + ")"), "omega2"),
    (re.compile(r"(?i)\b(?:partial\s*)?omega(?:-|_)?squared\s*=\s*(" + NUM + ")"), "omega2"),
    (re.compile(r"(?i)\b(?:cohen(?:'s)?\s*f|f)\s*=\s*(" + NUM + ")"), "f"),
    (re.compile(r"(?i)\b(?:phi|\u03c6)\s*=\s*(" + NUM + ")"), "phi"),
    (re.compile(r"(?i)\b(?:cramer(?:'s)?\s*[vV]|V)\s*=\s*(" + NUM + ")"), "V"),
]

CI_PATTERN = re.compile(
    r"(?i)(\d{2}(?:\.\d)?%?)\s*(?:CI|confidence\s+interval)[^\[\(]{0,20}"
    r"\[?\s*(" + NUM + r")\s*[,;-]\s*(" + NUM + r")\s*\]?")

# sample-size / design hints
N_PATTERN = re.compile(r"(?i)\bN\s*=\s*(\d+)")
N1_PATTERN = re.compile(r"(?i)\bn1\s*=\s*(\d+)")
N2_PATTERN = re.compile(r"(?i)\bn2\s*=\s*(\d+)")
M_PATTERN = re.compile(r"(?i)\b(?:df|m)\s*=\s*(\d+)")


# --- effect-size computation -------------------------------------------------

def _d_from_t(t, n1, n2):
    if t is None or n1 is None or n2 is None or n1 <= 0 or n2 <= 0:
        return None
    return t * np.sqrt(1.0 / n1 + 1.0 / n2)


def _g_from_t(t, n1, n2):
    d = _d_from_t(t, n1, n2)
    if d is None:
        return None
    df = n1 + n2 - 2
    if df <= 0:
        return None
    j = 1 - (3.0 / (4.0 * df - 1))
    return d * j


def _dz_from_t(t, n):
    if t is None or n is None or n < 2:
        return None
    return t / np.sqrt(n)


def _r_from_t(t, df):
    if t is None or df is None or df <= 0:
        return None
    return t / np.sqrt(t * t + df)


def _eta2_from_F(F, df1, df2):
    if F is None or df1 is None or df2 is None or F < 0 or df1 <= 0 or df2 <= 0:
        return None
    return (F * df1) / (F * df1 + df2)


def _omega2_from_F(F, df1, df2):
    if F is None or df1 is None or df2 is None or F < 0 or df1 <= 0 or df2 <= 0:
        return None
    num = F * df1 - df1
    den = F * df1 + df2 + 1
    if den <= 0:
        return None
    return max(0.0, num / den)


def _cohens_f_from_F(F, df1, df2):
    if F is None or df1 is None or df2 is None or F < 0 or df1 <= 0 or df2 <= 0:
        return None
    return np.sqrt((F * df1) / df2)


def _phi_from_chisq(chisq, N):
    if chisq is None or N is None or N <= 0:
        return None
    return np.sqrt(chisq / N)


def _V_from_chisq(chisq, N, m):
    if chisq is None or N is None or m is None or N <= 0 or m <= 0:
        return None
    return np.sqrt(chisq / (N * m))


# --- CI computation ----------------------------------------------------------

def _ci_d_ind_approx(d, n1, n2, level=0.95):
    if d is None or n1 is None or n2 is None or n1 <= 0 or n2 <= 0:
        return None
    N = n1 + n2
    if N <= 2:
        return None
    se_d = np.sqrt((N / (n1 * n2)) + (d * d / (2.0 * (N - 2))))
    z = stats.norm.ppf(1 - (1 - level) / 2)
    return (d - z * se_d, d + z * se_d)


def _fisher_ci_r(r, n, level=0.95):
    if r is None or n is None or n <= 3 or abs(r) >= 1:
        return None
    z = np.arctanh(r)
    se = 1.0 / np.sqrt(n - 3)
    zc = stats.norm.ppf(1 - (1 - level) / 2)
    return (np.tanh(z - zc * se), np.tanh(z + zc * se))


def _ci_eta2(F, df1, df2, level=0.95):
    """Noncentral-F inversion for partial eta^2 (Steiger 2004)."""
    if F is None or df1 is None or df2 is None or F < 0 or df1 <= 0 or df2 <= 0:
        return None
    alpha = 1 - level

    def ncf_cdf(lam):
        try:
            return stats.ncf.cdf(F, df1, df2, nc=lam)
        except Exception:  # noqa: BLE001
            return np.nan

    lo = _solve_lambda(lambda l: ncf_cdf(l) - (1 - alpha / 2), df1, df2, F)
    hi = _solve_lambda(lambda l: ncf_cdf(l) - (alpha / 2), df1, df2, F)
    if lo is None or hi is None:
        return None
    def eta(lam):
        return lam / (lam + df2)
    return (eta(lo), eta(hi))


def _solve_lambda(f, df1, df2, F):
    """Bisection over lambda in a wide window for the noncentral F cdf."""
    max_lam = 1000.0 * max(1.0, F)
    # bracket: cdf is monotone decreasing in lambda
    a, b = 0.0, max_lam
    try:
        fa = f(a)
        fb = f(b)
    except Exception:  # noqa: BLE001
        return None
    if fa == 0:
        return a
    if fb == 0:
        return b
    # If root not bracketed (f(a) and f(b) same sign) return None unless f(a) is
    # already past the target (then the limit is 0).
    if fa * fb > 0:
        if fa > 0:
            return 0.0
        return None
    for _ in range(120):
        mid = (a + b) / 2
        fm = f(mid)
        if fm == 0 or (b - a) < 1e-10:
            return mid
        if fa * fm < 0:
            b, fb = mid, fm
        else:
            a, fa = mid, fm
    return (a + b) / 2


def _ci_dz(dz, n, level=0.95):
    """Noncentral-t inversion for Cohen's dz (Algina & Keselman 2003)."""
    if dz is None or n is None or n < 2:
        return None
    df = n - 1
    t_obs = dz * np.sqrt(n)
    alpha = 1 - level

    def f_lo(nc):
        try:
            return stats.nct.ppf(1 - alpha / 2, df, nc) - t_obs
        except Exception:  # noqa: BLE001
            return np.nan

    def f_hi(nc):
        try:
            return stats.nct.ppf(alpha / 2, df, nc) - t_obs
        except Exception:  # noqa: BLE001
            return np.nan

    search = max(50.0, abs(t_obs) * 5 + 20)
    lo = _bisect_any(f_lo, -search, search)
    hi = _bisect_any(f_hi, -search, search)
    if lo is None or hi is None:
        return None
    return (lo / np.sqrt(n), hi / np.sqrt(n))


def _bisect_any(f, a, b):
    fa, fb = f(a), f(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:
        return None
    for _ in range(200):
        mid = (a + b) / 2
        fm = f(mid)
        if fm == 0 or (b - a) < 1e-10:
            return mid
        if fa * fm < 0:
            b, fb = mid, fm
        else:
            a, fa = mid, fm
    return (a + b) / 2


# --- consistency checks ------------------------------------------------------

_TOL = 0.02  # absolute tolerance for effect-size matching


def _match_effect(test, es_type, es_val, sentence):
    """Return (computed_value, status, note) for a reported effect size."""
    ttype = test.get("test_type")
    if ttype == "t":
        df = test["df"]
        t = test["stat"]
        if es_type == "r":
            exp = _r_from_t(t, df)
            return _cmp(es_val, exp, "r", t)
        if es_type in ("d", "g"):
            n1 = test.get("n1")
            n2 = test.get("n2")
            if n1 is None or n2 is None:
                return None, "SKIP", "needs n1/n2 to verify d/g from t"
            exp = _g_from_t(t, n1, n2) if es_type == "g" else _d_from_t(t, n1, n2)
            return _cmp(es_val, exp, es_type, t)
        if es_type == "dz":
            n = test.get("n1")
            if n is None:
                return None, "SKIP", "needs n to verify dz from t"
            exp = _dz_from_t(t, n)
            return _cmp(es_val, exp, "dz", t)
        return None, "SKIP", "no rule for %s from t" % es_type
    if ttype == "F":
        F = test["stat"]
        df1 = test["df1"]
        df2 = test["df2"]
        if es_type == "eta2":
            exp = _eta2_from_F(F, df1, df2)
            return _cmp(es_val, exp, "eta2", F)
        if es_type == "omega2":
            exp = _omega2_from_F(F, df1, df2)
            return _cmp(es_val, exp, "omega2", F)
        if es_type == "f":
            exp = _cohens_f_from_F(F, df1, df2)
            return _cmp(es_val, exp, "f", F)
        return None, "SKIP", "no rule for %s from F" % es_type
    if ttype == "chisq":
        chisq = test["stat"]
        N = test.get("n1")
        if es_type == "phi":
            if N is None:
                return None, "SKIP", "needs N to verify phi from chi-square"
            exp = _phi_from_chisq(chisq, N)
            return _cmp(es_val, exp, "phi", chisq)
        if es_type == "V":
            m = test.get("m")
            if N is None:
                return None, "SKIP", "needs N to verify Cramer's V"
            if m is None and test.get("df") == 1:
                m = 1  # a chi-square with df=1 is a 2x2 table -> min(r-1,c-1)=1
            if m is None:
                return None, "SKIP", "needs m to verify Cramer's V"
            exp = _V_from_chisq(chisq, N, m)
            return _cmp(es_val, exp, "V", chisq)
        return None, "SKIP", "no rule for %s from chi-square" % es_type
    return None, "SKIP", "unknown test type"


def _cmp(reported, computed, kind, stat):
    if reported is None or computed is None or not np.isfinite(computed):
        return None, "SKIP", "could not compute %s from statistic" % kind
    delta = abs(reported - computed)
    if delta <= _TOL:
        status = "PASS"
    else:
        # a large relative mismatch
        rel = delta / max(1e-9, abs(reported))
        status = "ERROR" if delta > 0.10 or rel > 0.20 else "WARN"
    note = "%s: reported %.3f, computed %.3f (diff %.3f)" % (
        kind, reported, computed, delta)
    return computed, status, note


def _check_ci(es_type, es_val, ci, test):
    """Return (status, note) for a reported CI against the point estimate."""
    lo, hi = ci
    if es_val is None or lo is None or hi is None:
        return "SKIP", "missing point estimate or CI bounds"
    if hi < lo:
        return "ERROR", "CI lower bound exceeds upper bound"
    # symmetry check: midpoint should equal the point estimate
    mid = (lo + hi) / 2
    if abs(mid - es_val) > max(0.05, 0.10 * abs(es_val)):
        return "WARN", "CI midpoint (%.3f) does not match point estimate (%.3f)" % (
            mid, es_val)
    # method-specific consistency where computable
    ttype = test.get("test_type")
    if es_type == "r":
        exp = _fisher_ci_r(es_val, test.get("n1"))
        if exp is not None:
            return _cmp_ci((lo, hi), exp, "r")
    if es_type == "eta2" and ttype == "F":
        exp = _ci_eta2(test["stat"], test["df1"], test["df2"])
        if exp is not None:
            return _cmp_ci((lo, hi), exp, "eta2")
    if es_type == "dz":
        exp = _ci_dz(es_val, test.get("n1"))
        if exp is not None:
            return _cmp_ci((lo, hi), exp, "dz")
    if es_type == "d" and test.get("n1") is not None and test.get("n2") is not None:
        exp = _ci_d_ind_approx(es_val, test["n1"], test["n2"])
        if exp is not None:
            return _cmp_ci((lo, hi), exp, "d")
    return "PASS", "CI is symmetric around the point estimate"


def _cmp_ci(reported, computed, kind):
    tol = 0.06  # CI bounds are wider, allow more slack
    delta = max(abs(reported[0] - computed[0]), abs(reported[1] - computed[1]))
    if delta <= tol:
        return "PASS", "%s CI matches (diff %.3f)" % (kind, delta)
    if delta > 0.20:
        return "ERROR", "%s CI mismatch (max diff %.3f)" % (kind, delta)
    return "WARN", "%s CI slightly off (max diff %.3f)" % (kind, delta)


# --- main module -------------------------------------------------------------

def _extract_tests(sentence):
    tests = []
    for m in T_PATTERN.finditer(sentence):
        tests.append({"test_type": "t", "df": int(m.group(1)),
                      "stat": float(m.group(2)), "raw": m.group(0)})
    for m in F_PATTERN.finditer(sentence):
        tests.append({"test_type": "F", "df1": int(m.group(1)),
                      "df2": int(m.group(2)), "stat": float(m.group(3)),
                      "raw": m.group(0)})
    for m in CHISQ_PATTERN.finditer(sentence):
        tests.append({"test_type": "chisq", "df": int(m.group(1)),
                      "stat": float(m.group(2)), "raw": m.group(0)})
    return tests


def _attach_context(tests, sentence):
    n = N_PATTERN.search(sentence)
    n1 = N1_PATTERN.search(sentence)
    n2 = N2_PATTERN.search(sentence)
    m = M_PATTERN.search(sentence)
    for t in tests:
        t["n1"] = int(n1.group(1)) if n1 else (int(n.group(1)) if n else None)
        t["n2"] = int(n2.group(1)) if n2 else None
        t["m"] = int(m.group(1)) if m else None
        t["sentence"] = sentence
    return tests


@register("es_check")
def es_check(paper, prev_outputs=None):
    sentences = text_search(paper, "[0-9]")
    rows = []
    if not sentences.empty:
        for _, r in sentences.iterrows():
            sentence = str(r["text"])
            tests = _extract_tests(sentence)
            es_found = []
            for regex, etype in ES_TOKENS:
                for mm in regex.finditer(sentence):
                    es_found.append({"type": etype, "value": float(mm.group(1))})
            ci_found = []
            for mm in CI_PATTERN.finditer(sentence):
                ci_found.append((float(mm.group(2)), float(mm.group(3))))
            if not tests and not (ci_found and es_found):
                continue
            tests = _attach_context(tests, sentence)
            if not tests:
                # no test statistic: still check CI symmetry vs the effect size
                pseudo = {"test_type": "none", "n1": None, "n2": None, "raw": ""}
                _attach_context([pseudo], sentence)
                for es in es_found:
                    for ci in ci_found:
                        status, note = _check_ci(es["type"], es["value"], ci, pseudo)
                        rows.append({
                            "paper_id": paper.paper_id,
                            "sentence": sentence,
                            "test": "",
                            "effect_type": es["type"] + " CI",
                            "reported": es["value"],
                            "computed": None,
                            "status": status,
                            "note": note,
                        })
                continue
            for test in tests:
                for es in es_found:
                    computed, status, note = _match_effect(
                        test, es["type"], es["value"], sentence)
                    rows.append({
                        "paper_id": paper.paper_id,
                        "sentence": sentence,
                        "test": test["raw"],
                        "effect_type": es["type"],
                        "reported": es["value"],
                        "computed": computed,
                        "status": status,
                        "note": note,
                    })
                # CI checks: associate with the most relevant reported effect.
                if ci_found and es_found:
                    es_type = es_found[0]["type"]
                    es_val = es_found[0]["value"]
                    for ci in ci_found:
                        status, note = _check_ci(es_type, es_val, ci, test)
                        rows.append({
                            "paper_id": paper.paper_id,
                            "sentence": sentence,
                            "test": test["raw"],
                            "effect_type": es_type + " CI",
                            "reported": es_val,
                            "computed": None,
                            "status": status,
                            "note": note,
                        })

    table = pd.DataFrame(rows)
    if table.empty:
        return module_output(table=table,
                             summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
                             traffic_light="na",
                             summary_text="No test statistic with a co-reported "
                                          "effect size or CI found.",
                             report=["No effect-size/CI consistency checks could "
                                     "be run (need a t/F/chi-square test with a "
                                     "co-reported effect size)."])

    n_pass = int((table["status"] == "PASS").sum())
    n_warn = int((table["status"] == "WARN").sum())
    n_err = int((table["status"] == "ERROR").sum())
    n_skip = int((table["status"] == "SKIP").sum())

    summary = table.groupby("paper_id", dropna=False).agg(
        es_checked=("status", "size"),
        es_pass=("status", lambda s: int((s == "PASS").sum())),
        es_warn=("status", lambda s: int((s == "WARN").sum())),
        es_error=("status", lambda s: int((s == "ERROR").sum())),
        es_skip=("status", lambda s: int((s == "SKIP").sum())),
    ).reset_index()

    if n_err:
        tl = "red"
        summary_text = (f"{n_err} effect-size/CI error{'s' if n_err != 1 else ''} "
                        f"found in reported statistics")
    elif n_warn:
        tl = "yellow"
        summary_text = (f"{n_warn} possible effect-size/CI mismatch"
                        f"{'es' if n_warn != 1 else ''}")
    else:
        tl = "green"
        summary_text = "Reported effect sizes and CIs appear internally consistent"

    err = table[table["status"].isin(["ERROR", "WARN"])]
    report = [summary_text,
              "This implements the core of EffectCheck (escicheck): it verifies "
              "that a reported effect size matches the value implied by the "
              "co-reported test statistic, and that a reported confidence "
              "interval is consistent with the point estimate. Only common "
              "effect sizes (d/g/dz/r, eta^2/omega^2/f, phi/V) are checked.",
              md_table(err if not err.empty else table,
                       ["test", "effect_type", "reported", "computed", "status",
                        "note"],
                       ["Test", "Effect", "Reported", "Computed", "Status",
                        "Note"])]

    return module_output(table=table, summary_table=summary,
                         traffic_light=tl, summary_text=summary_text,
                         report=report, na_replace=0)
