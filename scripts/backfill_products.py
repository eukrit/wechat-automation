"""Phase 2: Extract products from all ingested files (Excel + PDF).

Reads wechat_files with file_type in (price_list, spreadsheet, catalog, quotation),
uses appropriate extractor (Excel, PDF/pdfplumber, or Gemini Vision),
and upserts products into wechat_products collection.

Usage:
    python -m scripts.backfill_products [--dry-run] [--limit N] [--pdf-only] [--excel-only] [--gemini] [--max-size-mb N]
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
from wechat_automation import firestore_store

logger = logging.getLogger(__name__)

EXCEL_EXTENSIONS = {"xlsx", "xls"}
PDF_EXTENSIONS = {"pdf"}
EXTRACTABLE_TYPES = {"price_list", "spreadsheet", "catalog", "quotation"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract products from ingested files")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't save to Firestore")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    parser.add_argument("--pdf-only", action="store_true", help="Only process PDF files")
    parser.add_argument("--excel-only", action="store_true", help="Only process Excel files")
    parser.add_argument("--gemini", action="store_true", help="Use Gemini Vision for PDFs that fail pdfplumber")
    parser.add_argument("--max-size-mb", type=int, default=50, help="Skip files larger than N MB (default 50)")
    parser.add_argument("--skip-extracted", action="store_true", help="Skip files already marked product_extracted")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Gather files from all relevant types
    files: list[dict] = []
    for file_type in EXTRACTABLE_TYPES:
        files.extend(firestore_store.search_files(file_type=file_type, limit=500))

    # Deduplicate by file_id
    seen = set()
    unique_files = []
    for f in files:
        fid = f.get("file_id", "")
        if fid not in seen:
            seen.add(fid)
            unique_files.append(f)
    files = unique_files

    # Filter by extension
    if args.pdf_only:
        files = [f for f in files if f.get("file_extension", "") in PDF_EXTENSIONS]
    elif args.excel_only:
        files = [f for f in files if f.get("file_extension", "") in EXCEL_EXTENSIONS]
    else:
        files = [f for f in files if f.get("file_extension", "") in EXCEL_EXTENSIONS | PDF_EXTENSIONS]

    # Filter by size
    max_bytes = args.max_size_mb * 1024 * 1024
    files = [f for f in files if f.get("file_size_bytes", 0) <= max_bytes]

    # Skip already-extracted
    if args.skip_extracted:
        files = [f for f in files if f.get("status") != "product_extracted"]

    if args.limit:
        files = files[:args.limit]

    logger.info("Found %d files to process", len(files))

    total_products = 0
    total_files_processed = 0
    gemini_fallback_count = 0

    for i, file_doc in enumerate(files, 1):
        filename = file_doc.get("filename", "?")
        file_id = file_doc.get("file_id", "")
        source_path = file_doc.get("source_path", "")
        vendor_id = file_doc.get("vendor_id", "")
        vendor_name = file_doc.get("vendor_name", "")
        ext = file_doc.get("file_extension", "")

        logger.info("[%d/%d] Processing: %s", i, len(files), filename)

        local_path = Path(source_path) if source_path else None
        if local_path and not local_path.exists():
            local_path = None

        if not local_path:
            logger.warning("  Local file not found, skipping: %s", source_path)
            continue

        try:
            if ext in EXCEL_EXTENSIONS:
                products = extract_products_from_excel(
                    filepath=str(local_path),
                    source_file_id=file_id,
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                )
            elif ext in PDF_EXTENSIONS:
                products = extract_products_from_pdf(
                    filepath=str(local_path),
                    source_file_id=file_id,
                    vendor_id=vendor_id,
                    vendor_name=vendor_name,
                )
                # Gemini fallback for PDFs with no pdfplumber results
                if not products and args.gemini:
                    logger.info("  pdfplumber found nothing, trying Gemini Vision...")
                    from extractors.gemini_extractor import extract_products_gemini
                    products = extract_products_gemini(
                        filepath=str(local_path),
                        source_file_id=file_id,
                        vendor_id=vendor_id,
                        vendor_name=vendor_name,
                    )
                    if products:
                        gemini_fallback_count += 1
            else:
                continue
        except Exception as e:
            logger.error("  Extraction failed: %s", e)
            continue

        if not products:
            logger.info("  No products extracted")
            continue

        logger.info("  Extracted %d products", len(products))

        if not args.dry_run:
            saved = 0
            for product in products:
                try:
                    firestore_store.upsert_product(product)
                    saved += 1
                except Exception as e:
                    logger.error("  Failed to save product: %s", e)
            logger.info("  Saved %d products to Firestore", saved)

        total_products += len(products)
        total_files_processed += 1

        # Update file status
        if not args.dry_run:
            wf = firestore_store.get_file(file_id)
            if wf:
                wf.status = "product_extracted"
                firestore_store.upsert_file(wf)

    logger.info("=== Summary ===")
    logger.info("Files processed: %d / %d", total_files_processed, len(files))
    logger.info("Total products extracted: %d", total_products)
    if args.gemini:
        logger.info("Gemini fallback used: %d files", gemini_fallback_count)
    if args.dry_run:
        logger.info("(dry-run — nothing saved to Firestore)")


if __name__ == "__main__":
    main()
