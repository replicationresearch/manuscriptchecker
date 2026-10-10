# Benchmark results

Each run has a readable summary (`.txt`) and a text-free record per case
(`.json`) with the corpus hash, engine commit and code hash, options and
per-service search counts. A file ending in `_incomplete` had failed or
refused searches and must not be used as a baseline.

Results are observations of live search indexes on the stated date; they
change as the indexes do. Compare runs only on the same corpus version.

- `20261010_1828` - first run on corpus v2. It was made on the working tree
  that became the engine commit of this pull-request series (recorded as
  "uncommitted changes" with its code hash).
