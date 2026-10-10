# MüCOS Manuscript Checker

A portable Windows desktop app (plus a small web app) that turns a manuscript
(PDF / DOCX / DOC / HTML) into a formatted meta-scientific quality report.

It converts the document to TEI XML with **GROBID**, then runs one or more check
engines:

| Engine | What it does |
|--------|--------------|
| **metacheck (R)** | The original set of manuscript checks, via the R `metacheck` package. |
| **ChetaMeck (Python)** | An independent reimplementation of the metacheck checks, plus forensic metascience (GRIM/GRIMMER/DEBIT…), effect-size & CI consistency (EffectCheck port) and R2 editorial checks. |
| **Plagiarism Check** | Licence-free *verbatim* text-overlap detection: one exact phrase per paragraph is searched in open full texts (Europe PMC, OpenAlex, Wikipedia), then the best candidates' full texts and any local files are compared with the whole manuscript (shingles, after normalising formatting and UK/US spelling). |

You can select several engines at once — each one produces its own report.

## Getting started (desktop)

1. Double-click **`ManuscriptChecker.exe`** (or `Start Metacheck.bat`).
2. On first run the app automatically installs the R `metacheck` package if it
   is missing (you still need **R** installed). You can also run `setup.bat`
   once yourself.
3. Pick a manuscript, choose the GROBID server (defaults to a public TUE
   instance), select the engine(s) and checks, then press **Run check**.
4. Each report opens in your browser automatically.

## Copying to another PC (portable)

Copy the whole folder, then on the target PC:

1. Double-click `ManuscriptChecker.exe` — the metacheck package is installed
   automatically on first run if it is missing.

The target PC still needs **R** (+ the `metacheck` package), and **LibreOffice**
if you want to convert DOCX/HTML (PDFs work without it). GROBID is reached over
the internet by default.

## Web app

`run.bat` starts a local server (FastAPI) with an upload page; the same
pipeline and engines are used.

## Auto-update

The app checks the GitHub repo's latest release (via the GitHub Releases API)
on startup and via the **Check for updates** button in the *About* tab. When a
newer version is published, the new `ManuscriptChecker.exe` release asset is
downloaded and installed automatically on the next launch.

Releases are built and published automatically by the
`.github/workflows/release.yml` workflow. To publish:

1. Bump `config.py` → `DESKTOP_APP_VERSION`.
2. Commit the change and push a tag matching the version (e.g. `v0.7.0`):
   `git tag v0.7.0 && git push origin v0.7.0`. You can also trigger it manually
   from the **Actions** tab (the version is then read from `config.py`).
3. The release notes are generated from the commit history — edit them on the
   release page if you want custom notes.

## Tests

`tests/test_plagcheck.py` holds offline unit tests of the Plagiarism Check
engine: `python -m pytest tests`.

## Building yourself

```bat
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m PyInstaller metacheck.spec --noconfirm
```

## License / attribution

Not affiliated with the official metacheck app. For private use only.
Coded by DeepSeek V4 Flash · Prompted by Lukas Röseler.
