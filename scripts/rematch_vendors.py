"""Re-run vendor matching on all unmatched files.

Also seeds vendor aliases from WeChat OneDrive folder names into
the vendor matcher's knowledge base.

Usage:
    python -m scripts.rematch_vendors [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.onedrive_scanner import _parse_folder_name
from wechat_automation import firestore_store
from wechat_automation.vendor_matcher import VendorMatcher

logger = logging.getLogger(__name__)

# Additional vendor aliases from OneDrive folder names and known Chinese names
# Maps alias -> canonical vendor name to search for in go_vendors
EXTRA_ALIASES: dict[str, str] = {
    # From OneDrive folders
    "kaito": "Kaito",
    "haisan": "Haisan",
    "eva surf": "EVA Surf Products",
    "zhixing": "Zhixing Educational Toys",
    "perflex": "Changsha Perflex",
    "kihome": "Qihao Home Kihome",
    "qihao": "Qihao Home Kihome",
    "avant sports": "Avant Sports",
    "waytop": "Qingdao Waytop",
    "colin hpl": "Colin HPL",
    "bingyao": "Hebei BingYao",
    "laikeman": "Laikeman",
    "courtyard garden": "Courtyard Garden",
    "siki": "SIKI Lighting",
    "moonhill": "Moonhill",
    "you le jia": "YOU LE JIA",
    "guocio": "Aqara",
    "jingying": "Jingying Lighting",
    "kaiyuan": "KAIYUAN Lighting",
    "mason": "MASON Strip Light",
    "nanolux": "NANOLUX",
    "zm sculpture": "ZM Sculpture",
    "flyon": "Flyon Sport",
    "shangdong century": "Shangdong Century Sports",
    # Common Chinese vendor names from filenames
    "洪馨": "Hongxin",
    "庭院故事": "Courtyard Garden",
    "华富立": "Huafuli",
    "京图": "Jingtu",
    "追美": "Zhuimei",
    "将力": "Jiangli",
    "曼尼特": "Manitta",
    "佛洛伦克": "Florenk",
    "环星": "Huanxing",
    "必美": "Bimei",
    "博生": "Bosheng",
    "诗韵": "Shiyun",
    "美尚": "Meishang",
    "非常面子": "FOSB",
    "浪潮": "Langchao",
    "卫域": "Weiyu",
    "鸿政威": "Hongzhengwei",
    "捷觅": "Jiemi Lighting",
    "栢格": "Baige",
}


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

    # Inject extra aliases into the matcher
    injected = 0
    for alias, canonical in EXTRA_ALIASES.items():
        alias_lower = alias.lower()
        if alias_lower not in matcher._vendor_names:
            # Create a synthetic vendor entry
            matcher._vendor_names[alias_lower] = {
                "_doc_id": canonical.replace(" ", "_"),
                "name": canonical,
            }
            injected += 1
    logger.info("Injected %d extra vendor aliases (total: %d)", injected, len(matcher._vendor_names))

    # Get all unmatched files
    all_files = [d.to_dict() for d in firestore_store._db().collection("wechat_files").stream()]
    unmatched = [f for f in all_files if not f.get("vendor_id")]

    logger.info("Unmatched files: %d / %d total", len(unmatched), len(all_files))

    matched_count = 0
    for f in unmatched:
        filename = f.get("filename", "")
        folder = f.get("source_folder", "")
        parsed_vendor = f.get("parsed_vendor_name", "")

        result = matcher.match(vendor_hint=parsed_vendor, folder_name=folder)

        # Also try matching against the full filename
        if not result.vendor_id:
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
