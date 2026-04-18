# Changelog

## v0.9.0 — 2026-04-18

### Added
- **Sort options** in search bar dropdown:
  - Relevance (default, Firestore natural order)
  - Name A–Z / Name Z–A
  - Vendor A–Z / Vendor Z–A (secondary sort by product name)
  - Price Low → High (unpriced items pushed to end)
  - Price High → Low
  - SKU (A–Z)
  - Newest first (by `extracted_at`)
- `/api/products?sort=...` accepts all sort options, applied after filtering
- Sort persists in URL query params (omitted when default `relevance`)
- Sort excluded from breadcrumb (it's a preference, not a filter)
- `clearFilters()` also resets sort to relevance

### Files changed
- `web/app.py` — sort param + sort logic in `/api/products`
- `web/templates/index.html` — sort `<select>`, FILTER_FIELDS includes sort, clearFilters resets

### Outcome
- Browse by price discovery, alphabetical catalog, vendor grouping
- Shareable sorted URLs: `/?category=Lighting&sort=price_asc`
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.8.0 — 2026-04-18

### Added
- **Infinite scroll**: product grid auto-appends next 60 items as you scroll down
- `IntersectionObserver` watches a sentinel element 400px below the grid; triggers `search(true)` to append
- Status bar shows "Showing N of M" while more available, "All X products loaded" when done
- Fresh search/filter change resets offset + clears grid seamlessly
- Removed: prev/next page buttons, "Apply filters" button

### Files changed
- `web/templates/index.html` — new `search(append)` overload, `enableScrollObserver`, sentinel element, load-status bar

### Outcome
- Smoother browsing — no clicking through pages
- Single-page continuous experience on desktop and mobile
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.7.0 — 2026-04-18

### Added
- **URL slugs**: filter state serializes to query params. Example: `?category=Lighting&subcategory=Pendant+Lamp&vendor=Karhi+Lighting`
- **Breadcrumb navigation**: shows active filters as pills `All Products › 🏷️ Category: Lighting › 📦 Subcategory: Pendant Lamp › 🏪 Vendor: Karhi Lighting`
- Each breadcrumb pill has `×` to remove that single filter
- **Clear all** button appears when 2+ filters are active
- **All Products** home crumb resets to unfiltered view
- Browser **back/forward** restores prior filter state via `popstate`
- Direct URL links shareable — paste `/?category=Lighting&vendor=Moonhill` to pre-filter

### Files changed
- `web/templates/index.html` — breadcrumb CSS, URL sync (`syncUrl`, `applyUrlToFilters`), `renderBreadcrumb`, `removeFilter`, popstate handler

### Outcome
- Shareable filter URLs (copy-paste)
- Browser history works natively
- Visual chain shows where you are in the catalog hierarchy
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.6.1 — 2026-04-18

### Changed
- Thumbnails now use native `<img loading="lazy">` (was IntersectionObserver) — more reliable rendering
- Click thumbnail → loads high-res 1200px preview in simple fullscreen overlay (was modal with bar+download)
- Modal simplified to just the image + close button

### Added
- `/api/preview` supports `size=thumb` (400px) and `size=large` (1200px)
- PDF `size=large` renders at 3x zoom with JPEG quality 85

## v0.6.0 — 2026-04-18

### Added
- **Image modal**: clicking a thumbnail opens the image in a lightbox overlay (no more accidental download), with an explicit Download button in the modal bar
- **Interactive cascading filters**:
  * Selecting a category narrows the vendor dropdown to only vendors with products in that category
  * Selecting a vendor narrows categories + subcategories to that vendor's offerings
  * Selecting a subcategory further narrows vendors
- `/api/filters` now returns 5 cross-reference maps: `category_to_vendors`, `vendor_to_categories`, `vendor_to_subcategories`, `subcategory_to_category`, `subcategory_to_vendors` (5-minute in-memory cache)
- Preview endpoint returns a placeholder JPEG on rendering failure instead of HTTP 500
- Files >200MB skip rendering and return a placeholder

### Fixed
- Cloud Run memory was 512Mi → bumped to 2Gi + CPU 2 + 300s timeout + concurrency 10 (was OOM-crashing on large file preview)
- Lost HTTP/2 stream on some files (worked fine with HTTP/1.1 retry) — Cloud Run resource bump resolves

### Files changed
- `web/app.py` — expanded `/api/filters` response, size guardrail on previews
- `web/templates/index.html` — image modal, interactive filter logic, `onFilterChange()` cascading

### Outcome
- Lighting filter → 21 matching vendors shown
- Furniture filter → 36 matching vendors shown
- Preview click → modal (not download). Download button explicit.
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.5.0 — 2026-04-18

### Added
- **Responsive search**: 350ms debounced search-as-you-type on text input + all filters (Search button removed)
- **Product images**: 180px preview area on every card, lazy-loaded via IntersectionObserver
- `/api/preview/{file_id}?page=N` renders source file page as JPEG thumbnail
- PDF rendering via PyMuPDF (fitz) at 2x zoom → 400px JPEG q75
- Excel/PPTX preview: extracts first embedded image from `xl/media/` or `ppt/media/`
- Thumbnail cache in `gs://wechat-documents-attachments/_thumbnails/`
- Mobile responsive: sidebar collapses <900px, single-column cards <500px

### Fixed
- `generate_signed_url()` failure on Cloud Run (metadata creds lack private key) → stream bytes through FastAPI
- `/api/file/{id}/download` now streams source file directly with Content-Disposition

### Files changed
- `web/app.py` — preview + streaming download endpoints, PDF/xlsx/pptx rendering helpers
- `web/templates/index.html` — debounced search, lazy image loader, responsive CSS
- `web/requirements.txt` — pymupdf + pillow

### Outcome
- 34,582 products now show lazy-loaded thumbnails
- Search feels instant — results update while typing
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.4.1 — 2026-04-18

### Fixed
- Cloud Run index (`/`) returned 500 `unhashable type: 'dict'` when Jinja cached vendor dicts
- Moved vendor/category/subcategory population to client-side via `/api/filters`
- `index()` now returns minimal static HTML, all data loaded via AJAX

### Files changed
- `web/app.py` — new `/api/filters` endpoint, simplified index route
- `web/templates/index.html` — removed Jinja loops, added `loadFilters()` JS

### Outcome
- Index page returns 200; filters (19 categories, 1,348 subcategories, 94 vendors) populate dynamically
- Live: https://wechat-web-rg5gmtwrfa-as.a.run.app

## v0.4.0 — 2026-04-18

### Added
- FastAPI web app `web/app.py` deployed to Cloud Run (`wechat-web`)
- HTML UI `web/templates/index.html` with search bar, filters, product cards
- API endpoints: `/api/products`, `/api/vendors`, `/api/vendor/{id}`, `/api/file/{id}/download`, `/api/stats`, `/api/filters`, `/health`
- `web/Dockerfile` + `web/cloudbuild-web.yaml` for Cloud Run deployment
- Signed GCS URLs for file downloads from product cards

### Outcome
- Live at https://wechat-web-rg5gmtwrfa-as.a.run.app (allUsers can invoke)
- Handles 94 vendors, 498 files, 34,582 products

## v0.3.0 — 2026-04-18

### Added
- Product category + subcategory enrichment via Gemini 2.5 Flash (Vertex AI)
- `scripts/enrich_categories.py` batch-classifies existing products (80 per call)
- `sync_now.py` Phase 2b: auto-enriches up to 500 unclassified products per cycle
- `WeChatVendor.subcategories` field for vendor catalog browsing
- Updated Gemini prompt to require both category + subcategory

### Outcome
- 34,582 products classified 100% (category + subcategory)
- Categories: Furniture (13,570), Lighting (4,853), Hardware (2,334), Wall Panel (1,915), Playground (1,693)

## v0.2.0 — 2026-04-17

### Added
- `extractors/pdf_extractor.py` pdfplumber table extraction
- `extractors/gemini_extractor.py` Vertex AI Gemini Vision fallback
- `extractors/pptx_extractor.py` slide text + image extraction
- `scripts/convert_and_extract.py` DOCX/PPTX → PDF converter (python-docx, python-pptx, reportlab)
- `scripts/rematch_vendors.py` with 90+ vendor aliases
- `scripts/build_vendors.py` rebuilds `wechat_vendors` aggregation
- `scripts/sync_now.py` 15-min CRON pipeline: ingest → match → extract → rebuild vendors → status
- PDF chunking for oversized catalogs (adaptive sizing based on MB/page)
- GCS upload for files >20MB (Gemini Vision via URI)
- Switched from Gemini API key to GCP Service Account (Vertex AI)

### Outcome
- 408 files fully processed (84%)
- 34,582 products extracted (Excel 18,256 + Gemini 13,931 + pdfplumber 2,101)
- 92 vendors aggregated

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
