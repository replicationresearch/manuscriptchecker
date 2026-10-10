# Plagiarism benchmarks

Three layers, from fast and exact to slow and realistic:

1. **`tests/`** (repo root) - offline unit tests, run in seconds, no network:
   `python -m pytest tests`. All logic cases live here (quotes, declarations,
   same work / own work, cited sources, refused searches, corpus assembly,
   the PAN-style measures).
2. **`pan.py`** - the matcher alone on the PAN13 text-alignment corpus
   (downloaded separately; see the script header). Our own implementation of
   the PAN-style measures, not validated against the official scorer.
3. **`run_online.py`** - the whole engine against the live search services on
   the corpus in `corpus/`. Results are dated observations of live indexes.

## The corpus (`corpus/`)

- `hosts_synthetic/` - six manuscripts drafted with an LLM for this benchmark
  and dedicated to the public domain (CC0). Their text exists nowhere else.
- `hosts_real/` - body paragraphs of six CC BY articles from PubMed Central.
- `passages.json` - 72 short verbatim excerpts (1, 3 or 5 sentences): 18 each
  from PubMed Central, open-access articles outside PubMed Central, PsyArXiv
  and Wikipedia. Every source is CC BY, CC BY-SA or CC0, checked on the version
  that was downloaded; attribution is in `NOTICE.md`.
- `recipe.json` - which passage goes where. Hosts and passages are joined in
  memory only, so no mixed-licence text is distributed.

Each track (synthetic, real) holds every source class x insertion type three
times. The corpus is a pilot: 72 cases in 12 hosts. `build_corpus.py` rebuilt
it from live services; rerunning it gives a different corpus, so bump
`version` in the recipe if you do.

Only sources whose full text could be downloaded and licence-checked are in
the corpus. The benchmark therefore measures detection among obtainable open
texts, not coverage of scholarship in general.

## Running

    python scripts/plagbench/run_online.py --openalex-key KEY[,KEY...] --dry-run
    python scripts/plagbench/run_online.py --openalex-key KEY[,KEY...]

A full run searches about 1,200 phrases in each service. OpenAlex meters
searches (about 100 a day without a key, about 1,000 per free key); the engine
combines up to 20 phrases per search, so a full run needs roughly 250
(isolating boilerplate phrases and identifying matched phrases cost extra). A run in which any search failed or was refused is written as
`*_incomplete` and must not be used as a baseline.

`results/` holds a readable summary (`.txt`) and a text-free record per case
(`.json`) with the corpus hash, engine commit, options and search counts.
