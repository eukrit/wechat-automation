# Changelog

## v0.1.0 — 2026-04-10

### Added
- Initial project structure with full ingestion pipeline
- Firestore database `wechat-documents` (asia-southeast1) with collections: `wechat_files`, `wechat_products`, `wechat_contact_mapping`, `ingestion_log`
- GCS bucket `wechat-documents-attachments` for file storage
- `filename_parser.py` — extract date, vendor, project, doc type from filenames
- `file_classifier.py` — classify files by extension + keywords
- `vendor_matcher.py` — fuzzy match against `go_vendors` (shipping-automation) and `people_contacts` (default DB)
- `dat_decoder.py` — XOR decoder for WeChat .dat image files
- `gcs_store.py` — upload/download files to GCS
- `firestore_store.py` — CRUD for all wechat-documents collections + cross-DB reads
- `processor.py` — full ingestion pipeline orchestrator
- `file_watcher.py` — watchdog-based watcher with debouncing
- `onedrive_scanner.py` — scanner for WeChat OneDrive manual folders
- `initial_scan.py` — one-time backfill script
- `seed_vendor_aliases.py` — extract vendor names from folder structure
