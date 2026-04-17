"""Build/rebuild wechat_vendors collection by aggregating wechat_files and wechat_products.

Creates one vendor document per unique vendor_name, linking all files and product counts.

Usage:
    python -m scripts.build_vendors
"""

from __future__ import annotations

import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_automation import firestore_store
from wechat_automation.models import WeChatVendor

logger = logging.getLogger(__name__)

# Map file_type -> vendor field name
_TYPE_FIELD_MAP = {
    "catalog": "catalogs",
    "quotation": "quotations",
    "invoice": "invoices",
    "po": "purchase_orders",
    "price_list": "price_lists",
    "drawing": "drawings",
    "certificate": "certificates",
    "image": "images",
}


def _sanitize_id(name: str) -> str:
    """Create a Firestore-safe document ID from a vendor name."""
    s = name.strip().lower()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "_", s)
    s = s.strip("_")[:100]
    return s or "unknown"


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    db = firestore_store._db()

    # Load all files and products
    logger.info("Loading files and products...")
    all_files = [d.to_dict() for d in db.collection("wechat_files").stream()]
    all_products = [d.to_dict() for d in db.collection("wechat_products").stream()]

    logger.info("Files: %d, Products: %d", len(all_files), len(all_products))

    # Group files by vendor_name
    vendor_files: dict[str, list[dict]] = defaultdict(list)
    for f in all_files:
        vname = f.get("vendor_name", "").strip()
        if vname:
            vendor_files[vname].append(f)

    # Group products by vendor_name
    vendor_products: dict[str, list[dict]] = defaultdict(list)
    for p in all_products:
        vname = p.get("vendor_name", "").strip()
        if vname:
            vendor_products[vname].append(p)

    # Merge vendor names from both sources
    all_vendor_names = set(vendor_files.keys()) | set(vendor_products.keys())
    logger.info("Unique vendors: %d", len(all_vendor_names))

    # Build vendor documents
    vendors_created = 0
    for vname in sorted(all_vendor_names):
        files = vendor_files.get(vname, [])
        products = vendor_products.get(vname, [])

        vendor_id = _sanitize_id(vname)

        # File type breakdown
        type_counts = Counter(f.get("file_type", "other") for f in files)
        files_extracted = sum(1 for f in files if f.get("status") == "product_extracted")
        files_pending = len(files) - files_extracted

        # File IDs and size
        file_ids = [f.get("file_id", "") for f in files if f.get("file_id")]
        total_size = sum(f.get("file_size_bytes", 0) for f in files)

        # Most recent file date
        dates = [f.get("parsed_date", "") or f.get("ingested_at", "") for f in files]
        dates = [str(d) for d in dates if d]
        last_date = max(dates) if dates else ""

        # Cross-references (take first non-empty)
        go_vendor_id = ""
        peak_contact_code = ""
        people_contact_id = ""
        for f in files:
            if not go_vendor_id and f.get("vendor_id"):
                go_vendor_id = f["vendor_id"]
            if not peak_contact_code and f.get("peak_contact_code"):
                peak_contact_code = f["peak_contact_code"]
            if not people_contact_id and f.get("people_contact_id"):
                people_contact_id = f["people_contact_id"]

        # Product categories
        categories = list(set(
            p.get("category", "") for p in products if p.get("category")
        ))

        vendor = WeChatVendor(
            vendor_id=vendor_id,
            vendor_name=vname,
            go_vendor_id=go_vendor_id,
            peak_contact_code=peak_contact_code,
            people_contact_id=people_contact_id,
            file_ids=file_ids,
            file_count=len(files),
            product_count=len(products),
            catalogs=type_counts.get("catalog", 0),
            quotations=type_counts.get("quotation", 0),
            invoices=type_counts.get("invoice", 0),
            purchase_orders=type_counts.get("po", 0),
            price_lists=type_counts.get("price_list", 0),
            drawings=type_counts.get("drawing", 0),
            certificates=type_counts.get("certificate", 0),
            images=type_counts.get("image", 0),
            other_files=type_counts.get("document", 0) + type_counts.get("spreadsheet", 0)
                + type_counts.get("video", 0) + type_counts.get("presentation", 0)
                + type_counts.get("archive", 0) + type_counts.get("packing_list", 0)
                + type_counts.get("other", 0),
            files_extracted=files_extracted,
            files_pending=files_pending,
            last_file_date=last_date[:10] if last_date else "",
            total_size_bytes=total_size,
            categories=categories[:20],
            subcategories=list(set(p.get("subcategory", "") for p in products if p.get("subcategory")))[:50],
        )

        firestore_store.upsert_vendor(vendor)
        vendors_created += 1

    logger.info("=== Summary ===")
    logger.info("Vendors created/updated: %d", vendors_created)

    # Top vendors
    logger.info("\nTop vendors by file count:")
    for vname in sorted(all_vendor_names, key=lambda v: len(vendor_files.get(v, [])), reverse=True)[:20]:
        fc = len(vendor_files.get(vname, []))
        pc = len(vendor_products.get(vname, []))
        logger.info("  %s: %d files, %d products", vname, fc, pc)


if __name__ == "__main__":
    main()
