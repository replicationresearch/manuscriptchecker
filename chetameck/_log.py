"""Shared logger for ChetaMeck.

Individual check modules deliberately swallow exceptions (a network hiccup or
a malformed reference shouldn't crash the whole report), but a swallowed
exception used to vanish completely. Modules that catch-and-continue should
log at DEBUG level here instead, so ``logging.basicConfig(level=logging.DEBUG)``
(or ``--log-level debug`` if a caller wires that up) shows what actually
failed instead of a silently empty result.
"""

import logging

logger = logging.getLogger("chetameck")
