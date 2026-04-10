"""Phase 2: Extract products from all ingested price lists and spreadsheets.

Reads wechat_files with file_type in (price_list, spreadsheet), downloads
from GCS or reads from local source_path, runs the Excel extractor,
and upserts products into wechat_products collection.

Usage:
    python -m scripts.backfill_products [--dry-run] [--limit N]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from extractors.excel_extractor import extract_products_from_excel
from wechat_automation import firestore_store
from wechat_automation.models import WeChatProduct

logger = logging.getLogger(__name__)

# Extensions we can extract products from
EXTRACTABLE_EXTENSIONS = {"xlsx", "xls"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract products from ingested files")
    parser.add_argument("--dry-run", action="store_true", help="Extract but don't save to Firestore")
    parser.add_argument("--limit", type=int, default=0, help="Max files to process (0 = all)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Get all price_list and spreadsheet files
    files = firestore_store.search_files(file_type="price_list", limit=500)
    files += firestore_store.search_files(file_type="spreadsheet", limit=500)

    # Filter to extractable extensions only
    files = [f for f in files if f.get("file_extension", "") in EXTRACTABLE_EXTENSIONS]

    if args.limit:
        files = files[:args.limit]

    logger.info("Found %d extractable Excel files", len(files))

    total_products = 0
    total_files_processed = 0

    for i, file_doc in enumerate(files, 1):
        filename = file_doc.get("filename", "?")
        file_id = file_doc.get("file_id", "")
        source_path = file_doc.get("source_path", "")
        vendor_id = file_doc.get("vendor_id", "")
        vendor_name = file_doc.get("vendor_name", "")

        logger.info("[%d/%d] Processing: %s", i, len(files), filename)

        # Try local path first, fall back to GCS download
        local_path = Path(source_path) if source_path else None
        if local_path and not local_path.exists():
            local_path = None

        if not local_path:
            logger.warning("  Local file not found, skipping: %s", source_path)
            continue

        try:
            products = extract_products_from_excel(
                filepath=str(local_path),
                source_file_id=file_id,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
            )
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
    if args.dry_run:
        logger.info("(dry-run — nothing saved to Firestore)")


if __name__ == "__main__":
    main()
