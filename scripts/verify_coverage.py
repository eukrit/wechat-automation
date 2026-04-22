"""Verify that every file under the watched roots is captured + uploaded + parsed.

Walks wechat_auto_path and wechat_onedrive_path, SHA-256 hashes each watched file,
and compares against wechat_files in Firestore. Reports:
  - missing   : on disk but not in Firestore
  - no_gcs    : in Firestore but gcs_path empty
  - no_vendor : vendor_name empty
  - no_parse  : extractable file_type but status not in terminal set
  - parsed    : products extracted
  - empty     : parser returned 0 products
  - failed    : parser raised

Prints a summary and writes a detailed CSV to <log_dir>/coverage_report.csv.
"""

from __future__ import annotations

import csv
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from watcher.file_watcher import WATCH_EXTENSIONS
from wechat_automation import firestore_store

EXTRACTABLE_EXTS = {"xlsx", "xls", "pdf", "pptx", "docx", "doc", "jpg", "jpeg", "png", "webp"}
EXTRACTABLE_TYPES = {"price_list", "spreadsheet", "catalog", "quotation", "document", "invoice", "po"}


def _walk(root: Path):
    if not root.exists():
        return
    for p in root.rglob("*"):
        if p.is_file() and p.suffix.lower() in WATCH_EXTENSIONS:
            yield p


def main() -> None:
    settings = get_settings()
    roots = [Path(settings.wechat_auto_path), Path(settings.wechat_onedrive_path)]

    db = firestore_store._db()
    by_id = {d.id: d.to_dict() for d in db.collection("wechat_files").stream()}
    known_ids = set(by_id.keys())

    rows = []
    disk_counter: Counter = Counter()
    disk_ids: set[str] = set()

    for root in roots:
        print(f"Scanning {root}...")
        for fp in _walk(root):
            try:
                data = fp.read_bytes()
            except Exception as e:
                rows.append([str(fp), "", "read_error", str(e)])
                disk_counter["read_error"] += 1
                continue
            fid = hashlib.sha256(data).hexdigest()
            disk_ids.add(fid)
            doc = by_id.get(fid)
            if not doc:
                disk_counter["missing"] += 1
                rows.append([str(fp), fid[:12], "missing", ""])
                continue
            status = doc.get("status", "")
            gcs = doc.get("gcs_path", "")
            ext = doc.get("file_extension", "")
            ftype = doc.get("file_type", "")
            category = ""
            if ext in EXTRACTABLE_EXTS and ftype in EXTRACTABLE_TYPES:
                if status == "product_extracted":
                    category = "parsed"
                elif status == "extraction_empty":
                    category = "empty"
                elif status == "extraction_failed":
                    category = "failed"
                else:
                    category = "no_parse"
            else:
                category = "not_extractable"
            if not gcs:
                category = "no_gcs"
            elif not doc.get("vendor_name"):
                if category in ("parsed", "empty", "failed", "no_parse", "not_extractable"):
                    category = category + "+no_vendor"
            disk_counter[category] += 1
            rows.append([str(fp), fid[:12], category, status])

    orphan = known_ids - disk_ids
    disk_counter["in_db_not_on_disk"] = len(orphan)

    out = Path(settings.log_dir) / "coverage_report.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["path", "file_id_short", "category", "status"])
        for r in rows:
            w.writerow(r)
        for oid in orphan:
            d = by_id[oid]
            w.writerow([d.get("source_path", ""), oid[:12], "in_db_not_on_disk", d.get("status", "")])

    print("\n=== Coverage Summary ===")
    for k, v in sorted(disk_counter.items(), key=lambda kv: -kv[1]):
        print(f"  {k:30s} {v}")
    print(f"\nFiles on disk: {sum(v for k,v in disk_counter.items() if k != 'in_db_not_on_disk')}")
    print(f"Files in Firestore: {len(known_ids)}")
    print(f"Detailed report: {out}")


if __name__ == "__main__":
    main()
