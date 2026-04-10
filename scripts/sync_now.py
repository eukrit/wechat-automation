"""Full sync: scan for new files, match vendors, extract products.

Designed to run every 15 minutes via Task Scheduler.
Pipeline per file: ingest -> vendor match -> product extraction (Excel/PDF/Gemini).
Only processes NEW files (dedup via SHA-256 hash check in Firestore).
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.file_watcher import full_scan
from watcher.onedrive_scanner import scan_onedrive
from watcher.processor import FileProcessor
from wechat_automation import firestore_store

logger = logging.getLogger(__name__)

EXCEL_EXTENSIONS = {"xlsx", "xls"}
PDF_EXTENSIONS = {"pdf"}


def extract_products_for_file(file_doc: dict) -> int:
    """Extract products from a single ingested file. Returns product count."""
    file_id = file_doc.get("file_id", "")
    filename = file_doc.get("filename", "?")
    ext = file_doc.get("file_extension", "")
    source_path = file_doc.get("source_path", "")
    vendor_id = file_doc.get("vendor_id", "")
    vendor_name = file_doc.get("vendor_name", "")

    local_path = Path(source_path) if source_path else None
    if not local_path or not local_path.exists():
        return 0

    products = []

    try:
        if ext in EXCEL_EXTENSIONS:
            from extractors.excel_extractor import extract_products_from_excel
            products = extract_products_from_excel(
                filepath=str(local_path),
                source_file_id=file_id,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
            )
        elif ext in PDF_EXTENSIONS:
            from extractors.pdf_extractor import extract_products_from_pdf
            products = extract_products_from_pdf(
                filepath=str(local_path),
                source_file_id=file_id,
                vendor_id=vendor_id,
                vendor_name=vendor_name,
            )
            # Gemini fallback for PDFs with no pdfplumber results
            if not products:
                try:
                    from extractors.gemini_extractor import extract_products_gemini
                    products = extract_products_gemini(
                        filepath=str(local_path),
                        source_file_id=file_id,
                        vendor_id=vendor_id,
                        vendor_name=vendor_name,
                    )
                except Exception as e:
                    logger.debug("Gemini fallback failed for %s: %s", filename, e)
    except Exception as e:
        logger.warning("Product extraction failed for %s: %s", filename, e)
        return 0

    if not products:
        return 0

    saved = 0
    for product in products:
        try:
            firestore_store.upsert_product(product)
            saved += 1
        except Exception as e:
            logger.warning("Failed to save product from %s: %s", filename, e)

    # Update file status
    if saved:
        wf = firestore_store.get_file(file_id)
        if wf:
            wf.status = "product_extracted"
            firestore_store.upsert_file(wf)

    return saved


def main() -> None:
    settings = get_settings()

    # Set up logging
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "sync.log"),
            logging.StreamHandler(),
        ],
    )

    # --- Phase 1: Ingest new files ---
    processor = FileProcessor()
    new_files_total = 0

    auto_path = settings.wechat_auto_path
    if Path(auto_path).exists():
        count = full_scan(processor, auto_path)
        if count:
            logger.info("Auto-downloads: %d new files", count)
        new_files_total += count

    count = scan_onedrive(processor)
    if count:
        logger.info("OneDrive: %d new files", count)
    new_files_total += count

    # --- Phase 2: Extract products from newly ingested + any unprocessed files ---
    db = firestore_store._db()
    all_files = [d.to_dict() for d in db.collection("wechat_files").stream()]

    # Find files that need product extraction
    extractable_types = {"price_list", "spreadsheet", "catalog", "quotation", "document", "invoice", "po"}
    extractable_exts = EXCEL_EXTENSIONS | PDF_EXTENSIONS
    needs_extraction = [
        f for f in all_files
        if f.get("status") != "product_extracted"
        and f.get("file_extension", "") in extractable_exts
        and f.get("file_type", "") in extractable_types
        and f.get("file_size_bytes", 0) < 100 * 1024 * 1024  # skip > 100MB
    ]

    if needs_extraction:
        logger.info("Extracting products from %d files...", len(needs_extraction))
        total_products = 0
        for f in needs_extraction:
            count = extract_products_for_file(f)
            if count:
                logger.info("  %s: %d products", f.get("filename", "?")[:60], count)
                total_products += count

        if total_products:
            logger.info("Product extraction: %d products from %d files",
                        total_products, sum(1 for f in needs_extraction if extract_products_for_file(f)))

    # --- Summary ---
    if new_files_total:
        logger.info("Sync complete: %d new files ingested", new_files_total)
    else:
        logger.info("Sync complete: no new files")


if __name__ == "__main__":
    main()
