"""ChetaMeck engine: run check modules against a paper and collect results.

This mirrors the metacheck R package's ``report``/``module_run`` pipeline. Each
module is a Python function returning a dict with keys:

    table          : detailed per-item results (DataFrame)
    summary_table  : one row per paper with summary columns (DataFrame)
    traffic_light  : green | yellow | red | info | na | fail
    summary_text   : short summary string
    report         : list of HTML/markdown strings for the report section
    na_replace     : value(s) to fill NA in summary_table (optional)
"""

from .catalog import ONLINE_MODULE_NAMES
from .modules import registry

DEFAULT_MODULES = [
    "all_p_values", "all_urls", "marginal", "stat_p_exact", "stat_p_nonsig",
    "stat_check", "stat_effect_size", "es_check", "coi_check", "funding_check",
    "funding_coi_affiliation_check",
    "ref_consistency", "open_practices", "power", "repo_check", "code_check",
    "prereg_check", "prereg_statement", "ref_accuracy", "ref_replication", "ref_retraction",
    "ref_pubpeer", "ref_miscitation", "ref_summary",
    "grim_check", "grimmer_check", "sd_range_check", "sd_se_check",
    "debit_check", "stalt_check", "csf_check", "test_recalc",
    "r2_check", "df_consistency_check", "duplicate_check", "image_forensic_check",
    "causal_language_check", "reliability_check", "irb_ethics_check",
    "demographics_check", "multiple_comparisons_check",
    "exclusion_reporting_check", "likert_parametric_check",
    "interrater_reliability_check", "harking_check", "response_rate_check",
    "missing_data_check",
]

FAST_MODULES = [
    "all_p_values", "all_urls", "marginal", "stat_p_exact", "stat_p_nonsig",
    "stat_check", "stat_effect_size", "es_check", "coi_check", "funding_check",
    "funding_coi_affiliation_check",
    "ref_consistency", "open_practices", "power",
    "grim_check", "grimmer_check", "sd_range_check", "sd_se_check",
    "debit_check", "stalt_check", "csf_check", "test_recalc",
    "r2_check", "df_consistency_check", "duplicate_check", "image_forensic_check",
    "ref_miscitation", "prereg_statement",
    "causal_language_check", "reliability_check", "irb_ethics_check",
    "demographics_check", "multiple_comparisons_check",
    "exclusion_reporting_check", "likert_parametric_check",
    "interrater_reliability_check", "harking_check", "response_rate_check",
    "missing_data_check",
]

# Derived from the catalog's single source of truth (see catalog.py) instead
# of a hand-kept copy, so a module's online/offline status can't drift out of
# sync between the two lists (ref_summary aggregates other modules' results
# but makes no network call of its own, so it is *not* online).
ONLINE_MODULES = sorted(ONLINE_MODULE_NAMES)


def module_list(include_online=True):
    if include_online:
        return list(DEFAULT_MODULES)
    return list(FAST_MODULES)


def run_module(name, paper, prev_outputs=None):
    """Run a single named module, catching errors and normalizing output."""
    fn = registry.get(name)
    if fn is None:
        return _module_output(name, table=None, traffic_light="fail",
                              summary_text=f"Unknown module: {name}",
                              report=[f"Module `{name}` is not implemented."])
    try:
        res = fn(paper, prev_outputs=prev_outputs)
    except Exception as e:  # noqa: BLE001
        return _module_output(name, table=None, traffic_light="fail",
                              summary_text=f"{name} failed",
                              report=[f"**{name}** failed: {e}"])
    return _normalize(name, res, paper)


def _module_output(name, table, traffic_light, summary_text, report=None,
                   summary_table=None, na_replace=None):
    return {
        "module": name,
        "table": table if table is not None else __import__("pandas").DataFrame(),
        "summary_table": summary_table,
        "traffic_light": traffic_light,
        "summary_text": summary_text,
        "report": report or [],
        "na_replace": na_replace,
        "prev_outputs": {},
    }


def _normalize(name, res, paper):
    res = dict(res or {})
    res.setdefault("table", __import__("pandas").DataFrame())
    res.setdefault("traffic_light", "info")
    res.setdefault("summary_text", "")
    res.setdefault("report", [])
    res.setdefault("na_replace", None)
    if "summary_table" not in res or res["summary_table"] is None:
        res["summary_table"] = _default_summary(paper)
    res["module"] = name
    res["prev_outputs"] = {}
    return res


def _default_summary(paper):
    import pandas as pd
    return pd.DataFrame({"paper_id": [paper.paper_id]})


def run_modules(paper, modules=None, include_online=True, on_log=None):
    """Run a list of modules against a paper. Returns a list of outputs."""
    if modules is None:
        modules = module_list(include_online)
    outputs = []
    prev = {}
    for name in modules:
        if on_log:
            on_log(f"ChetaMeck: running {name}...")
        out = run_module(name, paper, prev_outputs=prev)
        out["prev_outputs"] = dict(prev)
        outputs.append(out)
        # stash table for later modules
        prev[name] = {"table": out["table"],
                      "traffic_light": out["traffic_light"]}
    return outputs


def run_chetameck(xml_path, modules=None, include_online=True, on_log=None,
                  pdf_path=None):
    """Parse a GROBID XML file, run modules and generate an HTML report.

    ``pdf_path``, when given, lets modules that need the original PDF (e.g.
    ``image_forensic_check``, which extracts embedded images) access it.

    Returns a dict with ``status``, ``report_html``, ``report_path``,
    ``outdir``, ``paper`` and ``outputs``.
    """
    from .paper import read_paper
    from .report import generate_report

    paper = read_paper(xml_path)
    paper.pdf_path = pdf_path
    if on_log:
        on_log(f"ChetaMeck: parsed {paper.paper_id}")
    outputs = run_modules(paper, modules=modules,
                          include_online=include_online, on_log=on_log)
    html_report = generate_report(paper, outputs, include_online=include_online)
    return {
        "status": "done",
        "paper": paper,
        "outputs": outputs,
        "report_html": html_report,
        "report_path": None,
        "outdir": None,
    }
