#!/usr/bin/env Rscript
# Reads a GROBID TEI XML file and produces a metacheck report.
#
# Usage:
#   Rscript metacheck_report.R --xml <file.xml> --outdir <dir> \
#       --name <stem> --modules mod1,mod2,...
#
# Outputs (written into --outdir):
#   metacheck_report_<title-slug>.html  (or .qmd if quarto rendering fails)
#   <name>_report.json  (structured summary of module results + errors)

suppressMessages({
  library(metacheck)
})

args <- commandArgs(trailingOnly = TRUE)

get_arg <- function(name, default = NULL) {
  i <- match(name, args)
  if (is.na(i) || i >= length(args)) return(default)
  args[[i + 1]]
}

xml_path  <- get_arg("--xml")
outdir    <- get_arg("--outdir")
name      <- get_arg("--name", tools::file_path_sans_ext(basename(xml_path)))
modules_s <- get_arg("--modules", "")

modules <- unlist(strsplit(modules_s, ","))
modules <- trimws(modules)
modules <- modules[nzchar(modules)]

stopifnot(!is.null(xml_path), file.exists(xml_path))
if (!dir.exists(outdir)) dir.create(outdir, recursive = TRUE)

# A small helper to write a JSON status file.
write_status <- function(status, error = NULL, format = NULL,
                         report_file = NULL, file = report_json) {
  jsonlite::write_json(
    list(status = status, error = error, format = format,
         paper_id = paper_id, report_file = report_file),
    file, auto_unbox = TRUE, pretty = TRUE
  )
}

paper_id <- NULL
paper <- NULL

# Shorten a title into a safe, filesystem-friendly slug. Keeps generated
# filenames short so the full output path stays under Windows' 260-char
# MAX_PATH (see pipeline.py's MAX_STEM_LEN, which enforces the same
# constraint for the Python/ChetaMeck engine - keep the two in sync).
title_slug <- function(title, maxlen = 50) {
  s <- gsub("[^A-Za-z0-9]+", "-", title)
  s <- gsub("^-+|-+$", "", s)
  s <- substr(s, 1, maxlen)
  s <- gsub("-+$", "", s)
  if (!nzchar(s)) s <- "report"
  s
}

tryCatch({
  # --- 1. Build the paper object from the GROBID XML ----------------------
  paper <- metacheck::read(xml_path)
  paper_id <- paper$paper_id

  # --- 2. Build a report filename from the manuscript title ---------------
  title <- paper$info$title[[1]]
  if (is.null(title) || is.na(title) || !nzchar(title)) title <- name
  report_base <- paste0("metacheck_report_", title_slug(title))
  html_file   <- file.path(outdir, paste0(report_base, ".html"))
  qmd_file    <- file.path(outdir, paste0(report_base, ".qmd"))
  report_json <- file.path(outdir, paste0(name, "_report.json"))

  # --- 3. Run the report (HTML via quarto, fall back to qmd) --------------
  res <- tryCatch(
    metacheck::report(paper, modules = modules,
                      output_format = "html", output_file = html_file),
    error = function(e) NULL
  )

  if (file.exists(html_file)) {
    write_status("done", format = "html", report_file = basename(html_file))
  } else if (file.exists(qmd_file)) {
    # quarto rendering failed but report() already fell back to qmd
    write_status("done", format = "qmd", report_file = basename(qmd_file))
  } else {
    # nothing was produced -> re-run as qmd only
    res <- tryCatch(
      metacheck::report(paper, modules = modules,
                        output_format = "qmd", output_file = qmd_file),
      error = function(e) NULL
    )
    if (file.exists(qmd_file)) {
      write_status("done", format = "qmd", report_file = basename(qmd_file))
    } else {
      write_status("error", error = "Report could not be generated. See console output.")
    }
  }
}, error = function(e) {
  write_status("error", error = conditionMessage(e))
})
