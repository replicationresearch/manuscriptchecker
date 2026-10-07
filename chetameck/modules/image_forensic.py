"""Basic image-forensics checks on figures extracted from the manuscript PDF.

Two heuristic checks, both meant to flag things for human review, not to
prove misconduct:

1. **Duplicate/reused image detection** - perceptual-hash comparison of every
   embedded raster image; flags images that are identical or near-identical
   to another image in the *same* manuscript (e.g. the same photo/blot/gel
   panel reused to represent two different experiments/conditions).
2. **Error Level Analysis (ELA)** - each image is re-saved as JPEG and diffed
   against the original; a large mean difference can indicate a spliced/edited
   region (the classic "different compression history" tell). It also fires
   on ordinary high-contrast figures (plots, line art, scans), so it is
   reported as "worth a look", never as proof of manipulation.

Needs PyMuPDF (``pip install pymupdf``) to pull images out of the PDF; if it
is not installed, or no PDF is available, the check reports "na" instead of
failing the whole run.
"""

import io

import pandas as pd
from PIL import Image, ImageChops

from .registry import register, module_output, md_table
from .._log import logger

try:
    import pymupdf as fitz  # PyMuPDF; `import fitz` is the deprecated alias
except Exception:  # noqa: BLE001
    try:
        import fitz  # noqa: F401  (older PyMuPDF versions only expose this name)
    except Exception:  # noqa: BLE001
        fitz = None

MIN_IMAGE_DIM = 80         # ignore tiny icons/logos/bullets
HASH_SIZE = 16              # average-hash grid (16x16 -> 256-bit hash)
DUP_HAMMING_THRESHOLD = 6   # near-identical if Hamming distance <= this
ELA_QUALITY = 90
ELA_FLAG_THRESHOLD = 45     # mean pixel diff (0-255) above which we flag
MAX_IMAGES = 150            # cap work on image-heavy PDFs


def _avg_hash(img):
    small = img.convert("L").resize((HASH_SIZE, HASH_SIZE), Image.LANCZOS)
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels) if pixels else 0
    bits = "".join("1" if p >= avg else "0" for p in pixels)
    return int(bits, 2) if bits else 0


def _hamming(a, b):
    return bin(a ^ b).count("1")


def _ela_score(img):
    """Mean absolute pixel difference between an image and a JPEG-recompressed copy."""
    buf = io.BytesIO()
    rgb = img.convert("RGB")
    rgb.save(buf, "JPEG", quality=ELA_QUALITY)
    buf.seek(0)
    recompressed = Image.open(buf)
    diff = ImageChops.difference(rgb, recompressed)
    hist = diff.convert("L").histogram()
    total = sum(hist)
    if not total:
        return 0.0
    return sum(i * c for i, c in enumerate(hist)) / total


def _extract_images(pdf_path):
    """Yield (image_index, page_number, PIL.Image) for embedded raster images."""
    doc = fitz.open(str(pdf_path))
    try:
        idx = 0
        for page_num in range(len(doc)):
            for img in doc[page_num].get_images(full=True):
                if idx >= MAX_IMAGES:
                    return
                xref = img[0]
                try:
                    base = doc.extract_image(xref)
                    im = Image.open(io.BytesIO(base["image"]))
                    im.load()
                    if im.width < MIN_IMAGE_DIM or im.height < MIN_IMAGE_DIM:
                        continue
                    idx += 1
                    yield idx, page_num + 1, im
                except Exception as e:  # noqa: BLE001
                    logger.debug("image_forensic_check: skipping image xref "
                                "%s on page %s: %s", xref, page_num + 1, e)
    finally:
        doc.close()


@register("image_forensic_check")
def image_forensic_check(paper, prev_outputs=None):
    pdf_path = getattr(paper, "pdf_path", None)
    if fitz is None:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="Image forensics unavailable (PyMuPDF not installed).",
            report=["Install `pymupdf` (`pip install pymupdf`) to enable the "
                    "image-duplication and Error-Level-Analysis checks."],
            na_replace=0)
    if not pdf_path:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na",
            summary_text="Image forensics unavailable (no PDF available).",
            report=["The original PDF was not available to this check."],
            na_replace=0)

    try:
        images = list(_extract_images(pdf_path))
    except Exception as e:  # noqa: BLE001
        logger.debug("image_forensic_check: failed to open %s: %s", pdf_path, e)
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="fail", summary_text="Image forensics failed.",
            report=[f"Could not read images from the PDF: {e}"], na_replace=0)

    if not images:
        return module_output(
            table=pd.DataFrame(),
            summary_table=pd.DataFrame({"paper_id": [paper.paper_id]}),
            traffic_light="na", summary_text="No embedded images found.",
            report=["No embedded raster images were found in the PDF "
                    "(vector-only figures are not checked by this module)."],
            na_replace=0)

    hashes = {}
    ela_rows = []
    for idx, page, im in images:
        try:
            hashes[idx] = (page, _avg_hash(im))
        except Exception as e:  # noqa: BLE001
            logger.debug("image_forensic_check: hash failed for image %s: %s", idx, e)
        try:
            score = _ela_score(im)
            if score >= ELA_FLAG_THRESHOLD:
                ela_rows.append({"image": f"page {page}, image {idx}",
                                 "check": "ELA", "detail": f"mean diff {score:.1f}"})
        except Exception as e:  # noqa: BLE001
            logger.debug("image_forensic_check: ELA failed for image %s: %s", idx, e)

    dup_rows = []
    seen_pairs = set()
    items = list(hashes.items())
    for i in range(len(items)):
        idx1, (page1, h1) = items[i]
        for j in range(i + 1, len(items)):
            idx2, (page2, h2) = items[j]
            dist = _hamming(h1, h2)
            if dist > DUP_HAMMING_THRESHOLD:
                continue
            key = tuple(sorted((idx1, idx2)))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            dup_rows.append({
                "image": f"page {page1}/img {idx1} <-> page {page2}/img {idx2}",
                "check": "duplicate/reused image",
                "detail": f"Hamming distance {dist}",
            })

    rows = dup_rows + ela_rows
    table = pd.DataFrame(rows)
    n_dup, n_ela = len(dup_rows), len(ela_rows)
    summary = pd.DataFrame({"paper_id": [paper.paper_id], "image_n": [len(images)],
                            "duplicate_images": [n_dup], "ela_flags": [n_ela]})

    if n_dup:
        tl = "red"
    elif n_ela:
        tl = "yellow"
    else:
        tl = "green"

    report = [f"{len(images)} embedded image{'s' if len(images) != 1 else ''} checked."]
    if len(table):
        report.append(md_table(table, ["image", "check", "detail"],
                               ["Image(s)", "Check", "Detail"]))
        if n_dup:
            report.append("**Duplicate/reused images** may indicate the same figure "
                          "was presented as two different experiments or panels - "
                          "verify manually.")
        if n_ela:
            report.append("**ELA flags** indicate a localized difference in JPEG "
                          "compression history, which *can* indicate splicing but "
                          "also fires on ordinary high-contrast figures (plots, "
                          "line art, scans) - treat as 'worth a manual look', not "
                          "proof of manipulation.")
    else:
        report.append("No duplicate images or ELA anomalies were detected.")

    summary_text = (f"{n_dup} duplicate image pair(s), {n_ela} ELA flag(s) across "
                    f"{len(images)} image(s).")
    return module_output(table=table, summary_table=summary, traffic_light=tl,
                         summary_text=summary_text, report=report, na_replace=0)
