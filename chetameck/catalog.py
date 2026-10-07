"""Module catalog: human-readable metadata for every ChetaMeck module.

Drives the module-selection UI and lets users pick which checks to run. Modules
are grouped by origin/category.
"""

# Module names that contact external services (CrossRef, OSF/GitHub API,
# RetractionWatch/PubPeer, ...). This is the single source of truth for "is
# module X online" - engine.py and pipeline.py both derive their FAST/ONLINE
# module lists from this set instead of keeping their own copies, which
# previously drifted out of sync (e.g. prereg_check - which resolves every OSF
# link via the OSF API - was miscategorized as offline in two places, so it
# kept running even with "include online checks" unticked).
ONLINE_MODULE_NAMES = {
    "ref_accuracy", "repo_check", "code_check", "ref_replication",
    "ref_retraction", "ref_pubpeer", "prereg_check",
}

# category -> (label, list of (module, friendly name, description))
CATEGORIES = {
    "metacheck": {
        "label": "Inherited from metacheck",
        "modules": [
            ("all_p_values", "All p-values", "List every p-value in the text"),
            ("all_urls", "All URLs", "List every URL in the main text"),
            ("marginal", "Marginal significance",
             "Flag effects described as 'marginally significant'"),
            ("stat_p_exact", "Imprecise p-values",
             "Flag p-values reported imprecisely or as exactly zero"),
            ("stat_p_nonsig", "Non-significant p-values",
             "Flag non-significant p-values for interpretation"),
            ("stat_check", "StatCheck", "Recompute t/F p-values to find errors"),
            ("stat_effect_size", "Effect sizes",
             "Check whether effect sizes are reported"),
            ("coi_check", "Conflict of interest",
              "Detect the actual COI statement(s)"),
            ("funding_check", "Funding", "Detect a funding statement"),
            ("ref_consistency", "Reference consistency",
              "Check in-text citations vs. bibliography"),
            ("open_practices", "Open practices",
              "Report whether the data are openly available or on request"),
            ("power", "Power analysis", "Find power analyses"),
            ("repo_check", "Repositories",
              "List OSF/GitHub/Zenodo repos referenced"),
            ("code_check", "Code review",
              "Review code files found via repo_check"),
            ("prereg_check", "Preregistration",
              "Find preregistration links"),
            ("prereg_statement", "Preregistration mentions",
              "Find sentences that mention preregistration / being registered"),
            ("ref_accuracy", "Reference accuracy",
             "Check reference metadata against CrossRef"),
            ("ref_replication", "Replications (FLoRA)",
             "Flag citations with a known replication"),
            ("ref_retraction", "Retractions",
             "Flag citations found in RetractionWatch"),
            ("ref_pubpeer", "PubPeer comments",
             "Flag citations with PubPeer comments"),
            ("ref_miscitation", "Miscitations",
             "Flag citations to frequently-miscited papers"),
            ("ref_summary", "Reference summary",
             "Summarize reference checks"),
        ],
    },
    "forensic": {
        "label": "Forensic metascience (Heathers)",
        "modules": [
            ("grim_check", "GRIM",
             "Is a reported mean possible for its sample size?"),
            ("grimmer_check", "GRIMMER",
             "Do mean/SD/n imply a whole-number sum of squares?"),
            ("sd_range_check", "Quick SD check",
             "SD must not exceed the max for its range"),
            ("sd_se_check", "SD/SE confusion",
             "Was a standard error reported as an SD?"),
            ("debit_check", "DEBIT",
             "Is a binary variable's mean/SD consistent?"),
            ("stalt_check", "STALT",
             "Does 'p < x' hide a much smaller true p?"),
            ("csf_check", "CSF omnibus",
             "Combine p-values to detect homogeneity"),
            ("test_recalc", "Recalculate t-tests",
             "Recompute independent-samples t-tests from descriptives"),
        ],
    },
    "r2": {
        "label": "R2 initial editorial assessment",
        "modules": [
            ("r2_check", "R2 editorial checks",
             "Run the automatable R2 initial assessment checklist"),
        ],
    },
    "esci": {
        "label": "Effect-size & CI consistency (EffectCheck)",
        "modules": [
            ("es_check", "Effect size & CI consistency",
             "Verify reported effect sizes and confidence intervals against the "
             "test statistic (escicheck port)"),
        ],
    },
    "integrity": {
        "label": "Data & content integrity",
        "modules": [
            ("duplicate_check", "Internal duplicate text",
             "Flag verbatim or near-duplicate passages recycled within the "
             "manuscript (self-plagiarism / salami slicing)"),
            ("image_forensic_check", "Image forensics",
             "Detect duplicate/reused figures and localized JPEG-compression "
             "anomalies (Error Level Analysis) in embedded images"),
            ("df_consistency_check", "Sample size / df consistency",
             "Check whether reported test statistics' degrees of freedom are "
             "consistent with the manuscript's own stated sample size"),
            ("funding_coi_affiliation_check", "Funding/COI vs. affiliation",
             "Cross-check author affiliations against the funding statement "
             "and the conflict-of-interest disclosure"),
        ],
    },
    "socialsci": {
        "label": "Social science methodology",
        "modules": [
            ("causal_language_check", "Causal language",
             "Flag causal wording ('led to', 'effect of X on Y') when no "
             "experimental-design marker is found"),
            ("reliability_check", "Scale reliability",
             "Check whether reported scales/questionnaires have a "
             "reliability coefficient (Cronbach's alpha, omega, ICC, ...)"),
            ("irb_ethics_check", "Ethics approval",
             "Detect an ethics approval / IRB / informed consent statement"),
            ("demographics_check", "Sample demographics",
             "Check whether age, gender/sex and sample origin are reported"),
            ("multiple_comparisons_check", "Multiple comparisons",
             "Flag many p-values reported with no correction method mentioned"),
            ("exclusion_reporting_check", "Exclusion reporting",
             "Check whether participant/case exclusions are justified"),
            ("likert_parametric_check", "Likert + parametric tests",
             "Flag parametric tests on Likert/ordinal data with no "
             "justification"),
            ("interrater_reliability_check", "Inter-rater reliability",
             "Check whether coded/rated data reports kappa, ICC or percent "
             "agreement"),
            ("harking_check", "HARKing (heuristic)",
             "Flag confirmatory-sounding hypothesis language with no "
             "preregistration detected"),
            ("response_rate_check", "Survey methodology",
             "Check response-rate reporting and online-panel quality "
             "controls (attention checks, ...)"),
            ("missing_data_check", "Missing data handling",
             "Check whether a missing-data handling method is described "
             "when missing data/attrition is mentioned"),
        ],
    },
}


def all_modules(include_online=True):
    """Return the flat list of module names across all categories."""
    names = []
    for cat in CATEGORIES.values():
        for name, _label, _desc in cat["modules"]:
            names.append(name)
    if not include_online:
        names = [n for n in names if n not in ONLINE_MODULE_NAMES]
    return names


def module_label(name):
    for cat in CATEGORIES.values():
        for mname, label, _desc in cat["modules"]:
            if mname == name:
                return label
    return name


def module_desc(name):
    for cat in CATEGORIES.values():
        for mname, _label, desc in cat["modules"]:
            if mname == name:
                return desc
    return ""


def module_category(name):
    for cat_name, cat in CATEGORIES.items():
        for mname, _label, _desc in cat["modules"]:
            if mname == name:
                return cat_name
    return "metacheck"
