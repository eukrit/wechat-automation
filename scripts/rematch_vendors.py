"""Re-run vendor matching on all unmatched files.

Uses centralized vendor aliases from wechat_automation/vendor_aliases.py.
The VendorMatcher auto-loads these aliases, so this script just re-runs
matching on all unlinked files.

Usage:
    python -m scripts.rematch_vendors [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from wechat_automation import firestore_store
from wechat_automation.vendor_matcher import VendorMatcher

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-match vendors on unlinked files")
    parser.add_argument("--dry-run", action="store_true", help="Show matches without saving")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    matcher = VendorMatcher()
    matcher._load()
    logger.info("Vendor names loaded: %d", len(matcher._vendor_names))

    # Get all unmatched files
    all_files = [d.to_dict() for d in firestore_store._db().collection("wechat_files").stream()]
    unmatched = [f for f in all_files if not f.get("vendor_id") and not f.get("vendor_name")]

    logger.info("Unmatched files: %d / %d total", len(unmatched), len(all_files))

    matched_count = 0
    for f in unmatched:
        filename = f.get("filename", "")
        folder = f.get("source_folder", "")
        parsed_vendor = f.get("parsed_vendor_name", "")

        result = matcher.match(vendor_hint=parsed_vendor, folder_name=folder)

        # Also try matching against the full filename
        if not result.vendor_id and not result.vendor_name:
            result = matcher.match(vendor_hint=filename, folder_name="")

        if result.vendor_id or result.vendor_name:
            matched_count += 1
            vendor_display = result.vendor_name or result.vendor_id
            logger.info("  MATCH: %s -> %s (%s, %.0f%%)",
                        filename[:60], vendor_display, result.match_method, result.confidence * 100)

            if not args.dry_run:
                wf = firestore_store.get_file(f.get("file_id", ""))
                if wf:
                    wf.vendor_id = result.vendor_id
                    wf.vendor_name = result.vendor_name
                    wf.vendor_match_method = result.match_method
                    wf.vendor_match_confidence = result.confidence
                    wf.people_contact_id = result.people_contact_id
                    wf.peak_contact_code = result.peak_contact_code
                    wf.status = "vendor_linked"
                    firestore_store.upsert_file(wf)

    logger.info("=== Summary ===")
    logger.info("Previously unmatched: %d", len(unmatched))
    logger.info("Newly matched: %d", matched_count)
    logger.info("Still unmatched: %d", len(unmatched) - matched_count)
    if args.dry_run:
        logger.info("(dry-run — nothing saved)")


if __name__ == "__main__":
    main()
