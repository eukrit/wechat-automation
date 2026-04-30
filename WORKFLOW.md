# WeChat Automation — Workflow & Data Model

## Sources (on-disk)

| Source | Path | Picked up by |
|---|---|---|
| WeChat desktop auto-downloads | `C:\Users\eukri\OneDrive\Documents\xwechat_files\wxid_5i25oznpj6ox12_309f\msg\file\` | `watcher.file_watcher` (watchdog + full-scan) |
| Manually curated OneDrive tree | `C:\Users\eukri\OneDrive\Documents\Documents GO\WeChat OneDrive\` | `watcher.onedrive_scanner` (recursive) |
| **Organized target (new)** | `...\WeChat OneDrive\WeChat Auto Downloads\<Category>\<Vendor>\YYYY-MM-DD_<filename>` | same scanner — duplicates reconciled by SHA |

## Sync pipeline (runs every 15 min via `scripts/sync_now.bat`)

```
Phase 1  Ingest           file_watcher.full_scan + onedrive_scanner.scan_onedrive
                          └─ processor.process_file:
                               hash -> dedup -> parse filename -> classify ->
                               upload to GCS -> vendor match -> upsert wechat_files
                               └─ (dup SHA at new path) reconcile source_path

Phase 2  Extract products Excel / PDF / PPTX / Gemini extractors →
                          firestore_store.upsert_product
                          Terminal statuses: product_extracted |
                          extraction_empty | extraction_failed

Phase 2b Enrich category  scripts.enrich_categories.classify_batch (Gemini)
                          updates wechat_products.category + subcategory

Phase 2c Auto-organize    scripts.organize_downloads.organize_all(
                             apply=True, move=True,
                             update_firestore=True, only_unorganized=True)
                          Moves new files into
                          WeChat Auto Downloads/<Category>/<Vendor>/YYYY-MM-DD_<name>
                          Updates source_path + organized_path in Firestore.

Phase 3  Rebuild vendors  rebuild_vendors(all_files, all_products) →
                          upsert_vendor (one doc per vendor_name)

Phase 4  Status           upsert_sync_status (completed | failed)
```

## Firestore DB: `wechat-documents` (project `ai-agents-go`)

| Collection | Doc ID | Purpose | Written by |
|---|---|---|---|
| `wechat_files` | SHA-256 of file bytes | One row per ingested file. Holds source_path, organized_path, gcs_path, vendor link, file_type, status, timestamps. | `processor.process_file`, `sync_now.extract_products_for_file` (status), `organize_downloads.organize_all` (paths) |
| `wechat_products` | auto | Products extracted from files. Links back via `source_file_id`. Has category/subcategory, pricing, vendor. | extractors (`excel`, `pdf`, `pptx`, `gemini`), `enrich_categories` |
| `wechat_vendors` | sanitized `vendor_name` | Per-vendor rollup: file_ids, counts per file_type, categories, total size, last_file_date. Rebuilt each sync. | `sync_now.rebuild_vendors` |
| `wechat_contact_mapping` | WeChat contact hash | Maps msg/attach/<hash>/ directories to known vendors (people_contact_id, peak_contact_code). | `scripts/build_vendors.py`, manual seeds |
| `sync_status` | `YYYYMMDD_HHMMSS_<uuid>` (+ `latest`) | One doc per sync run: files_new/extracted, products_new, errors, timestamps. | `sync_now.main` |
| `ingestion_log` | auto | Audit trail: file_uploaded, vendor_matched, error events. | `processor.process_file` via `firestore_store.log_event` |

### Cross-DB references

| Field in `wechat_files` / `wechat_vendors` | Points to | DB |
|---|---|---|
| `vendor_id` | `go_vendors` | `shipping-automation` |
| `people_contact_id` | `people_contacts` | default DB |
| `peak_contact_code` | Peak contact code | Peak Accounting (external) |
| `shipping_order_ids[]` | `shipping_orders` | `shipping-automation` |

## GCS

- Bucket: `gs://wechat-documents-attachments/`
- Layout: `<file_type>/<YYYY-MM>/<filename>`
- Stored as `gcs_path` on every `wechat_files` doc.

## Web app (`web/app.py`, FastAPI, Cloud Run `asia-southeast1`)

| Route | Purpose |
|---|---|
| `/` | Product browser (templates/index.html) |
| `/api/filters` | Vendors / categories / subcategories (cached) |
| `/api/products` | Faceted search + sort |
| `/api/stats` | Counts |
| `/preview/<file_id>` | Rendered page thumbnails from GCS |
| `/file/<file_id>` | Download/stream source file |
| `/sync-report` | **HTML dashboard**: recent `sync_status` docs, file status/type/ext breakdown, last 200 lines of `sync.log` |
| `/health` | liveness |

## Operational scripts (`scripts/`)

| Script | What it does |
|---|---|
| `sync_now.py` / `sync_now.bat` | Full pipeline (Phases 1–4). Scheduled task entry-point. |
| `start_watcher.bat` | Long-running watchdog + periodic full-scan. |
| `verify_coverage.py` | Hashes every on-disk file, diffs vs. Firestore, writes `coverage_report.csv`. |
| `organize_downloads.py` | Manual one-off organize; also invoked programmatically from sync. Dry-run by default. |
| `enrich_categories.py` | Batch-classify products → category/subcategory (Gemini). |
| `rematch_vendors.py` | Re-run vendor matching across all files. |
| `backfill_products.py` | Re-extract products for files missing them. |
| `build_vendors.py` | Seed `wechat_vendors` from external vendor master. |
| `seed_vendor_aliases.py` | Populate alias table used by `vendor_matcher`. |

## File status lifecycle (`wechat_files.status`)

```
ingested → vendor_linked | needs_vendor_link
            │
            └── (extraction phase) → product_extracted
                                   → extraction_empty
                                   → extraction_failed
```

Terminal statuses (skipped on subsequent sync cycles): `product_extracted`, `extraction_empty`, `extraction_failed`.

## Credentials

- Service account key: `Credentials Claude Code/ai-agents-go-0d28f3991b7b.json`
- Env var: `GOOGLE_APPLICATION_CREDENTIALS` (set in `scripts/*.bat`)
- All live secrets: GCP Secret Manager in `ai-agents-go`.
