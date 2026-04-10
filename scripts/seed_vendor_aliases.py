"""Seed vendor aliases from WeChat OneDrive folder names.

Scans the manually organized WeChat OneDrive folder and extracts
vendor names from folder naming conventions:
- "2026-04-08 Moonhill Climbing Wall" -> vendor alias "Moonhill Climbing Wall"
- "WeChat China Lighting/CDN Lighting" -> vendor alias "CDN Lighting"

Outputs a YAML file for manual review and contact hash mapping.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from watcher.onedrive_scanner import _parse_folder_name
from config.settings import get_settings

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    settings = get_settings()
    onedrive_path = Path(settings.wechat_onedrive_path)

    if not onedrive_path.exists():
        logger.error("Path not found: %s", onedrive_path)
        return

    vendors: list[dict] = []
    categories: dict[str, list[str]] = {}

    for item in sorted(onedrive_path.iterdir()):
        if not item.is_dir():
            continue

        vendor_name, date_str, category = _parse_folder_name(item.name)

        if category:
            # Category folder — list sub-vendor folders
            sub_vendors = [
                sub.name for sub in sorted(item.iterdir()) if sub.is_dir()
            ]
            categories[category] = sub_vendors
            for sv in sub_vendors:
                vendors.append({
                    "name": sv,
                    "category": category,
                    "source_folder": f"{item.name}/{sv}",
                })
        elif vendor_name:
            file_count = sum(1 for f in item.rglob("*") if f.is_file())
            vendors.append({
                "name": vendor_name,
                "date": date_str,
                "file_count": file_count,
                "source_folder": item.name,
            })

    # Print results
    logger.info("=== Vendor Names from OneDrive Folders ===\n")
    for v in vendors:
        cat = v.get("category", "")
        date = v.get("date", "")
        fc = v.get("file_count", "")
        prefix = f"[{cat}]" if cat else f"[{date}]" if date else ""
        suffix = f"({fc} files)" if fc else ""
        logger.info("  %s %s %s", prefix, v["name"], suffix)

    logger.info("\n=== Categories ===\n")
    for cat, subs in categories.items():
        logger.info("  %s: %s", cat, ", ".join(subs))

    logger.info("\nTotal unique vendor names: %d", len(vendors))


if __name__ == "__main__":
    main()
