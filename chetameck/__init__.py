"""ChetaMeck - a Python reimplementation of the metacheck checks.

ChetaMeck parses a GROBID TEI XML file into a structured paper object and runs
a set of quality checks on it, producing an HTML report. It is an independent
reimplementation of the `metacheck` R package's logic, written in Python.

The output report is clearly labelled as a ChetaMeck report (not a metacheck
report) and includes a disclaimer that it is not affiliated with the official
metacheck project.
"""

from .paper import read_paper, Paper
from .engine import run_modules, run_chetameck, DEFAULT_MODULES, FAST_MODULES, ONLINE_MODULES

__all__ = [
    "read_paper",
    "Paper",
    "run_modules",
    "run_chetameck",
    "DEFAULT_MODULES",
    "FAST_MODULES",
    "ONLINE_MODULES",
    "REPORT_APP_VERSION",
]

REPORT_APP_VERSION = "0.5.2"
