"""Phase 2: Extract products from ALL ingested files.

Supports: Excel (openpyxl/xlrd), PDF (pdfplumber + Gemini), PPTX/DOCX/images (Gemini).
Gemini 2.5 Flash is the default for any file that pdfplumber can't handle.

Usage:
    python -m scripts.backfill_products [--skip-extracted] [--limit N] [--all]
    python -m scripts.backfill_products --pdf-only --skip-extracted
    python -m scripts.backfill_products --all --skip-extracted  # process EVERYTHING
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from extractors.excel_extractor import extract_products_from_excel
from extractors.pdf_extractor import extract_products_from_pdf
from extractors.gemini_extractor import extract_products_gemini
from wechat_automation import firestore_store

logger = logging.getLogger(__name__)

EXCEL_EXTENSIONS = {"xlsx", "xls"}
PDF_EXTENSIONS = {"pdf"}
GEMINI_EXTENSIONS = {"pdf", "pptx", "docx", "doc", "jpg", "jpeg", "png", "webp", "bmp", "gif"}
ALL_EXTRACTABLE = EXCEL_EXTENSIONS | GEMINI_EXTENSIONS


def process_one_file(file_doc: dict, use_gemini: bool = True) -> int:
    """Extract products from one file. Returns product count."""
    file_id = file_doc.get("file_id", "")
    filename = file_doc.get("filename", "?")
    ext = file_doc.get("file_extension", "")
    source_path = file_doc.get("source_path", "")
    vendor_id = file_doc.get("vendor_id", "")
    vendor_name = file_doc.get("vendor_name", "")

    local_path = Path(source_path) if source_path else None
    if not local_path or not local_path.exists():
        logger.warning("  File not found: %s", source_path)
        return 0

    products = []

    try:
        # Strategy 1: Excel files — use openpyxl/xlrd (free, fast)
        if ext in EXCEL_EXTENSIONS:
            products = extract_products_from_excel(
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )
            # Gemini fallback for Excel files that openpyxl can't parse
            if not products and use_gemini and ext in GEMINI_EXTENSIONS:
                products = extract_products_gemini(
                    filepath=str(local_path), source_file_id=file_id,
                    vendor_id=vendor_id, vendor_name=vendor_name,
                )

        # Strategy 2: PDF — try pdfplumber first, then Gemini
        elif ext in PDF_EXTENSIONS:
            products = extract_products_from_pdf(
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )
            if not products and use_gemini:
                products = extract_products_gemini(
                    filepath=str(local_path), source_file_id=file_id,
                    vendor_id=vendor_id, vendor_name=vendor_name,
                )

        # Strategy 3: PPTX, DOCX, images — Gemini only
        elif ext in GEMINI_EXTENSIONS and use_gemini:
            products = extract_products_gemini(
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )

    except Exception as e:
        logger.error("  Extraction failed: %s", e)
        return 0

    if not products:
        return 0

    saved = 0
    for product in products:
        try:
            firestore_store.upsert_product(product)
            saved += 1
        except Exception as e:
            logger.error("  Failed to save product: %s", e)

    # Update file status
    if saved:
        wf = firestore_store.get_file(file_id)
        if wf:
            wf.status = "product_extracted"
            firestore_store.upsert_file(wf)

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract products from all ingested files")
    parser.add_argument("--skip-extracted", action="store_true", help="Skip files already marked product_extracted")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    parser.add_argument("--pdf-only", action="store_true", help="Only process PDF files")
    parser.add_argument("--excel-only", action="store_true", help="Only process Excel files")
    parser.add_argument("--all", action="store_true", help="Process ALL file types (PDF+Excel+PPTX+DOCX+images)")
    parser.add_argument("--no-gemini", action="store_true", help="Disable Gemini (Excel+pdfplumber only)")
    parser.add_argument("--max-size-mb", type=int, default=700, help="Skip files larger than N MB (default 700)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Load ALL files from Firestore
    db = firestore_store._db()
    files = [d.to_dict() for d in db.collection("wechat_files").stream()]

    # Filter by extension
    if args.pdf_only:
        files = [f for f in files if f.get("file_extension", "") in PDF_EXTENSIONS]
    elif args.excel_only:
        files = [f for f in files if f.get("file_extension", "") in EXCEL_EXTENSIONS]
    elif args.all:
        files = [f for f in files if f.get("file_extension", "") in ALL_EXTRACTABLE]
    else:
        files = [f for f in files if f.get("file_extension", "") in EXCEL_EXTENSIONS | PDF_EXTENSIONS]

    # Filter by size
    max_bytes = args.max_size_mb * 1024 * 1024
    files = [f for f in files if f.get("file_size_bytes", 0) <= max_bytes]

    # Skip already-extracted
    if args.skip_extracted:
        files = [f for f in files if f.get("status") != "product_extracted"]

    # Sort: smaller files first (faster wins early)
    files.sort(key=lambda f: f.get("file_size_bytes", 0))

    if args.limit:
        files = files[:args.limit]

    use_gemini = not args.no_gemini
    logger.info("Found %d files to process (Gemini: %s)", len(files), "ON" if use_gemini else "OFF")

    total_products = 0
    total_files_processed = 0

    for i, file_doc in enumerate(files, 1):
        filename = file_doc.get("filename", "?")
        size_mb = file_doc.get("file_size_bytes", 0) / 1024 / 1024
        logger.info("[%d/%d] %s (%.0fMB)", i, len(files), filename[:70], size_mb)

        count = process_one_file(file_doc, use_gemini=use_gemini)
        if count:
            logger.info("  -> %d products extracted", count)
            total_products += count
            total_files_processed += 1
        else:
            logger.info("  -> no products")

    logger.info("=== Summary ===")
    logger.info("Files processed: %d / %d", total_files_processed, len(files))
    logger.info("Total products extracted: %d", total_products)


if __name__ == "__main__":
    main()
