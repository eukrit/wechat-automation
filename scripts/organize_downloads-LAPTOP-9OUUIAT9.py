"""Reorganize WeChat downloads into Category/Vendor/YYYY-MM-DD_filename layout.

Target root: C:\\Users\\eukri\\OneDrive\\Documents\\Documents GO\\WeChat OneDrive\\WeChat Auto Downloads

Usage:
    python -m scripts.organize_downloads                  # dry-run, writes plan CSV
    python -m scripts.organize_downloads --apply          # copy files to new layout
    python -m scripts.organize_downloads --apply --move   # move instead of copy
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from wechat_automation import firestore_store

TARGET_ROOT = Path(r"C:\Users\eukri\OneDrive\Documents\Documents GO\WeChat OneDrive\WeChat Auto Downloads")

_WIN_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_MULTI_WS = re.compile(r"\s+")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")


def sanitize(name: str, fallback: str = "_Unknown") -> str:
    name = _WIN_INVALID.sub("-", (name or "").strip())
    name = _MULTI_WS.sub(" ", name).strip(" .")
    return name[:120] or fallback


def pick_category(vendor_name: str, vendor_doc: dict | None, product_cat_map: dict[str, Counter]) -> str:
    # 1) vendor's own categories list
    if vendor_doc:
        cats = vendor_doc.get("categories") or []
        cats = [c for c in cats if c and c.lower() != "other"]
        if cats:
            return cats[0]
    # 2) most common category across this vendor's products
    if vendor_name and vendor_name in product_cat_map:
        top = product_cat_map[vendor_name].most_common(1)
        if top and top[0][0] and top[0][0].lower() != "other":
            return top[0][0]
    return "_Uncategorized"


def pick_date(f: dict) -> str:
    pd = (f.get("parsed_date") or "").strip()
    if pd and _DATE_RE.match(pd):
        return pd[:10]
    for key in ("file_created_at", "file_modified_at", "ingested_at"):
        v = f.get(key)
        if isinstance(v, datetime):
            return v.astimezone(timezone.utc).strftime("%Y-%m-%d")
        if isinstance(v, str) and _DATE_RE.match(v):
            return v[:10]
    return "0000-00-00"


def target_path(f: dict, category: str) -> Path:
    vendor = sanitize(f.get("vendor_name") or "", "_Unknown Vendor")
    cat = sanitize(category or "", "_Uncategorized")
    date = pick_date(f)
    orig = f.get("filename") or "unknown.bin"
    # Strip any leading YYYY-MM-DD_ or YYYY-MM-DD<space> to avoid duplication
    orig = re.sub(r"^\d{4}-\d{2}-\d{2}[\s_-]+", "", orig)
    orig = sanitize(orig, "unknown.bin")
    return TARGET_ROOT / cat / vendor / f"{date}_{orig}"


def safe_unique(path: Path, file_id: str) -> Path:
    if not path.exists():
        return path
    # If existing file has the same SHA, treat as identical → reuse (caller will skip copy).
    try:
        existing_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        if existing_sha == file_id:
            return path  # same content, no rename needed
    except Exception:
        pass
    # Different content with the same name → suffix with short file_id
    stem, ext = path.stem, path.suffix
    return path.with_name(f"{stem}_{file_id[:8]}{ext}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Execute the plan (default: dry-run)")
    ap.add_argument("--move", action="store_true", help="Move instead of copy")
    ap.add_argument("--update-firestore", action="store_true",
                    help="On apply, set organized_path on each wechat_files doc")
    args = ap.parse_args()

    settings = get_settings()
    db = firestore_store._db()

    # Build vendor doc lookup + product category counts by vendor
    vendor_docs = {d.id: d.to_dict() for d in db.collection("wechat_vendors").stream()}
    vendor_by_name = {v.get("vendor_name", ""): v for v in vendor_docs.values() if v.get("vendor_name")}

    product_cat_map: dict[str, Counter] = defaultdict(Counter)
    for d in db.collection("wechat_products").stream():
        p = d.to_dict()
        vn = p.get("vendor_name", "")
        cat = p.get("category", "")
        if vn and cat:
            product_cat_map[vn][cat] += 1

    files = [d.to_dict() for d in db.collection("wechat_files").stream()]
    plan_rows = []
    stats = Counter()

    for f in files:
        src = f.get("source_path", "")
        fid = f.get("file_id", "")
        if not src or not Path(src).exists():
            stats["src_missing"] += 1
            plan_rows.append([fid[:12], src, "", "SKIP-missing-source"])
            continue
        vname = f.get("vendor_name", "")
        cat = pick_category(vname, vendor_by_name.get(vname), product_cat_map)
        tgt = target_path(f, cat)
        tgt = safe_unique(tgt, fid)
        action = "OK"
        if tgt.exists():
            try:
                same = hashlib.sha256(tgt.read_bytes()).hexdigest() == fid
            except Exception:
                same = False
            action = "SKIP-already" if same else "RENAME-dup"
            stats["already"] += 1
        else:
            stats["to_move"] += 1
        plan_rows.append([fid[:12], src, str(tgt), action])

    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    plan_path = log_dir / "organize_plan.csv"
    with plan_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["file_id", "source_path", "target_path", "action"])
        w.writerows(plan_rows)

    print("=== Plan ===")
    for k, v in stats.items():
        print(f"  {k:20s} {v}")
    print(f"  total rows: {len(plan_rows)}")
    print(f"Plan CSV: {plan_path}")

    if not args.apply:
        print("\nDry-run only. Re-run with --apply to execute.")
        return

    print(f"\nApplying plan ({'MOVE' if args.move else 'COPY'})...")
    done = err = 0
    for fid_short, src, tgt, action in plan_rows:
        if not tgt or action.startswith("SKIP"):
            continue
        srcp, tgtp = Path(src), Path(tgt)
        try:
            tgtp.parent.mkdir(parents=True, exist_ok=True)
            if args.move:
                shutil.move(str(srcp), str(tgtp))
            else:
                shutil.copy2(str(srcp), str(tgtp))
            done += 1
            if args.update_firestore:
                for f in files:
                    if f.get("file_id", "").startswith(fid_short):
                        doc_id = f["file_id"]
                        db.collection("wechat_files").document(doc_id).update({
                            "organized_path": str(tgtp),
                        })
                        break
        except Exception as e:
            err += 1
            print(f"  ERROR {src} -> {tgt}: {e}")

    print(f"Done: {done} files {'moved' if args.move else 'copied'}, {err} errors.")


if __name__ == "__main__":
    main()
