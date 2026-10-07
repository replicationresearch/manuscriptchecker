"""ChetaMeck check modules.

Each module is a function ``<name>(paper, prev_outputs=None)`` returning a dict
with ``table``, ``summary_table``, ``traffic_light``, ``summary_text``,
``report``, and optionally ``na_replace``.

Importing this package triggers registration of every built-in module into the
global ``registry`` via the ``@register`` decorator.
"""

from .registry import registry

# Importing each module registers it (the @register decorator runs at import).
from . import all_p_values
from . import all_urls
from . import marginal
from . import stat_p_exact
from . import stat_p_nonsig
from . import stat_check
from . import stat_effect_size
from . import es_check
from . import coi_check
from . import funding_check
from . import ref_consistency
from . import open_practices
from . import power
from . import repo_check
from . import code_check
from . import prereg_check
from . import prereg_statement
from . import ref_accuracy
from . import ref_replication
from . import ref_retraction
from . import ref_pubpeer
from . import ref_miscitation
from . import ref_summary
from . import forensic
from . import r2_check
from . import duplicate_check
from . import image_forensic
from . import df_consistency
from . import affiliation_check
from . import causal_language
from . import reliability_check
from . import irb_ethics_check
from . import demographics_check
from . import multiple_comparisons_check
from . import exclusion_reporting_check
from . import likert_parametric_check
from . import interrater_reliability_check
from . import harking_check
from . import response_rate_check
from . import missing_data_check

__all__ = ["registry"]
