"""Full sync pipeline: ingest -> match -> extract -> build vendors -> report status.

Designed to run every 15 minutes via Task Scheduler / CRON.
Pipeline: scan for new files -> vendor match -> product extraction -> update wechat_vendors -> write sync_status.
"""

from __future__ import annotations

import logging
import sys
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.file_watcher import full_scan
from watcher.onedrive_scanner import scan_onedrive
from watcher.processor import FileProcessor
from wechat_automation import firestore_store
from wechat_automation.models import SyncStatus, WeChatVendor

logger = logging.getLogger(__name__)

EXCEL_EXTENSIONS = {"xlsx", "xls"}
PDF_EXTENSIONS = {"pdf"}
PPTX_EXTENSIONS = {"pptx"}
GEMINI_EXTENSIONS = {"docx", "doc", "jpg", "jpeg", "png", "webp"}
EXTRACTABLE_EXTS = EXCEL_EXTENSIONS | PDF_EXTENSIONS | PPTX_EXTENSIONS | GEMINI_EXTENSIONS
EXTRACTABLE_TYPES = {"price_list", "spreadsheet", "catalog", "quotation", "document", "invoice", "po"}


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
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )
        elif ext in PDF_EXTENSIONS:
            from extractors.pdf_extractor import extract_products_from_pdf
            products = extract_products_from_pdf(
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )
            if not products:
                try:
                    from extractors.gemini_extractor import extract_products_gemini
                    products = extract_products_gemini(
                        filepath=str(local_path), source_file_id=file_id,
                        vendor_id=vendor_id, vendor_name=vendor_name,
                    )
                except Exception as e:
                    logger.debug("Gemini fallback failed for %s: %s", filename, e)
        elif ext == "pptx":
            from extractors.pptx_extractor import extract_products_from_pptx
            products = extract_products_from_pptx(
                filepath=str(local_path), source_file_id=file_id,
                vendor_id=vendor_id, vendor_name=vendor_name,
            )
        elif ext in ("docx", "doc", "jpg", "jpeg", "png", "webp"):
            try:
                from extractors.gemini_extractor import extract_products_gemini
                products = extract_products_gemini(
                    filepath=str(local_path), source_file_id=file_id,
                    vendor_id=vendor_id, vendor_name=vendor_name,
                )
            except Exception as e:
                logger.debug("Gemini failed for %s: %s", filename, e)
    except Exception as e:
        logger.warning("Extraction failed for %s: %s", filename, e)
        wf = firestore_store.get_file(file_id)
        if wf:
            wf.status = "extraction_failed"
            wf.processing_errors.append(str(e)[:500])
            firestore_store.upsert_file(wf)
        return 0

    if not products:
        wf = firestore_store.get_file(file_id)
        if wf:
            wf.status = "extraction_empty"
            firestore_store.upsert_file(wf)
        return 0

    saved = 0
    for product in products:
        try:
            firestore_store.upsert_product(product)
            saved += 1
        except Exception:
            pass

    wf = firestore_store.get_file(file_id)
    if wf:
        wf.status = "product_extracted" if saved else "extraction_empty"
        firestore_store.upsert_file(wf)

    return saved


def rebuild_vendors(all_files: list[dict], all_products: list[dict]) -> int:
    """Rebuild wechat_vendors collection from current files + products."""
    import re

    vendor_files: dict[str, list[dict]] = defaultdict(list)
    for f in all_files:
        vname = f.get("vendor_name", "").strip()
        if vname:
            vendor_files[vname].append(f)

    vendor_products: dict[str, list[dict]] = defaultdict(list)
    for p in all_products:
        vname = p.get("vendor_name", "").strip()
        if vname:
            vendor_products[vname].append(p)

    all_vendor_names = set(vendor_files.keys()) | set(vendor_products.keys())

    for vname in all_vendor_names:
        files = vendor_files.get(vname, [])
        products = vendor_products.get(vname, [])
        vid = re.sub(r"[^\w\u4e00-\u9fff]+", "_", vname.strip().lower()).strip("_")[:100] or "unknown"

        type_counts = Counter(f.get("file_type", "other") for f in files)
        file_ids = [f.get("file_id", "") for f in files if f.get("file_id")]
        dates = [str(d) for f in files for d in [f.get("parsed_date", "")] if d]

        vendor = WeChatVendor(
            vendor_id=vid, vendor_name=vname,
            go_vendor_id=next((f["vendor_id"] for f in files if f.get("vendor_id")), ""),
            peak_contact_code=next((f["peak_contact_code"] for f in files if f.get("peak_contact_code")), ""),
            people_contact_id=next((f["people_contact_id"] for f in files if f.get("people_contact_id")), ""),
            file_ids=file_ids, file_count=len(files), product_count=len(products),
            catalogs=type_counts.get("catalog", 0),
            quotations=type_counts.get("quotation", 0),
            invoices=type_counts.get("invoice", 0),
            purchase_orders=type_counts.get("po", 0),
            price_lists=type_counts.get("price_list", 0),
            drawings=type_counts.get("drawing", 0),
            certificates=type_counts.get("certificate", 0),
            images=type_counts.get("image", 0),
            other_files=sum(c for t, c in type_counts.items() if t not in
                          {"catalog","quotation","invoice","po","price_list","drawing","certificate","image"}),
            files_extracted=sum(1 for f in files if f.get("status") == "product_extracted"),
            files_pending=sum(1 for f in files if f.get("status") != "product_extracted"),
            last_file_date=max(dates)[:10] if dates else "",
            total_size_bytes=sum(f.get("file_size_bytes", 0) for f in files),
            categories=list(set(p.get("category", "") for p in products if p.get("category")))[:20],
            subcategories=list(set(p.get("subcategory", "") for p in products if p.get("subcategory")))[:50],
        )
        firestore_store.upsert_vendor(vendor)

    return len(all_vendor_names)


def main() -> None:
    settings = get_settings()

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    stream_handler = logging.StreamHandler(sys.stdout)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_dir / "sync.log", encoding="utf-8"),
            stream_handler,
        ],
    )

    # Initialize sync status
    sync = SyncStatus(
        sync_id=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6],
        status="running",
    )
    firestore_store.upsert_sync_status(sync)

    try:
        # --- Phase 1: Ingest new files ---
        processor = FileProcessor()
        new_total = 0

        auto_path = settings.wechat_auto_path
        if Path(auto_path).exists():
            count = full_scan(processor, auto_path)
            new_total += count

        count = scan_onedrive(processor)
        new_total += count

        sync.files_new = new_total
        if new_total:
            logger.info("Phase 1: %d new files ingested", new_total)

        # --- Phase 2: Extract products from unprocessed files ---
        db = firestore_store._db()
        all_files = [d.to_dict() for d in db.collection("wechat_files").stream()]

        TERMINAL_STATUSES = {"product_extracted", "extraction_empty", "extraction_failed"}
        needs_extraction = [
            f for f in all_files
            if f.get("status") not in TERMINAL_STATUSES
            and f.get("file_extension", "") in EXTRACTABLE_EXTS
            and f.get("file_type", "") in EXTRACTABLE_TYPES
            and f.get("file_size_bytes", 0) < 100 * 1024 * 1024
        ]

        products_new = 0
        files_extracted = 0
        errors = 0
        for f in needs_extraction:
            try:
                count = extract_products_for_file(f)
                if count:
                    files_extracted += 1
                    products_new += count
                    logger.info("  Extracted %d products from %s", count, f.get("filename", "?")[:60])
            except Exception as e:
                errors += 1
                sync.error_details.append(f"{f.get('filename','?')}: {e}")

        sync.files_extracted = files_extracted
        sync.products_new = products_new
        sync.extraction_errors = errors

        if products_new:
            logger.info("Phase 2: %d products from %d files", products_new, files_extracted)

        # --- Phase 2b: Enrich new products with category + subcategory ---
        try:
            from scripts.enrich_categories import classify_batch
            db = firestore_store._db()
            from google.cloud import firestore as fs
            unclassified = [
                (d.id, d.to_dict())
                for d in db.collection("wechat_products")
                .where(filter=fs.FieldFilter("subcategory", "==", ""))
                .limit(500)
                .stream()
            ]
            if unclassified:
                logger.info("Enriching %d products with category/subcategory...", len(unclassified))
                for i in range(0, len(unclassified), 80):
                    batch = unclassified[i:i + 80]
                    classifications = classify_batch([p for _, p in batch])
                    for (pid, _), cls in zip(batch, classifications):
                        try:
                            db.collection("wechat_products").document(pid).update({
                                "category": str(cls.get("category", "") or "Other"),
                                "subcategory": str(cls.get("subcategory", "") or ""),
                            })
                        except Exception:
                            pass
                logger.info("Category enrichment done")
        except Exception as e:
            logger.warning("Category enrichment failed: %s", e)

        # --- Phase 3: Rebuild vendor collection ---
        all_files = [d.to_dict() for d in db.collection("wechat_files").stream()]
        all_products = [d.to_dict() for d in db.collection("wechat_products").stream()]

        vendor_count = rebuild_vendors(all_files, all_products)

        # --- Phase 4: Write final status ---
        matched = sum(1 for f in all_files if f.get("vendor_name"))
        sync.status = "completed"
        sync.completed_at = datetime.now(timezone.utc)
        sync.total_files = len(all_files)
        sync.total_products = len(all_products)
        sync.total_vendors = vendor_count
        sync.files_vendor_matched = matched
        sync.files_unmatched = len(all_files) - matched
        sync.files_scanned = len(all_files)

        firestore_store.upsert_sync_status(sync)

        logger.info("=== Sync Complete ===")
        logger.info("Files: %d (matched: %d)", len(all_files), matched)
        logger.info("Products: %d (new: %d)", len(all_products), products_new)
        logger.info("Vendors: %d", vendor_count)

    except Exception as e:
        sync.status = "failed"
        sync.error_details.append(str(e))
        sync.completed_at = datetime.now(timezone.utc)
        firestore_store.upsert_sync_status(sync)
        logger.exception("Sync failed: %s", e)
        raise


if __name__ == "__main__":
    main()
