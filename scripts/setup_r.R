# One-time setup / update for the metacheck R package.
# metacheck is published as a precompiled binary on R-universe, so we install
# directly from there. This avoids any source compilation (and the need for
# Rtools), and works both when the package is missing and when updating.
# Usage:
#   Rscript setup_r.R          -> install only if missing
#   Rscript setup_r.R update   -> (re)install the latest binary
args <- commandArgs(trailingOnly = TRUE)
update <- "update" %in% args

repo <- "https://scienceverse.r-universe.dev"
options(repos = c(UNIVERSE = repo, CRAN = "https://cloud.r-project.org"))

install_pkg <- function() {
  install.packages("metacheck", repos = repo, type = "binary", quiet = TRUE)
}

if (update || !requireNamespace("metacheck", quietly = TRUE)) {
  if (update) {
    cat("Installing the latest metacheck binary from R-universe...\n")
  } else {
    cat("metacheck not found - installing from R-universe...\n")
  }
  install_pkg()
}

cat("metacheck:",
    if (requireNamespace("metacheck", quietly = TRUE)) {
      as.character(packageVersion("metacheck"))
    } else {
      "NOT INSTALLED"
    },
    "\n")
