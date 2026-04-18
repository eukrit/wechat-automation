# WeChat Automation — Claude Code Instructions

## Project Overview
Auto-ingest WeChat vendor file downloads into Firestore + GCS, link to existing vendors, extract product data. Watches local WeChat download folder and syncs to cloud.

## Key Rules

### Code Control
- **Primary branch:** `main` — auto-deploys via Cloud Build on push
- **Always commit with Co-Authored-By:** `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
- **Version tags:** Use semantic versioning (vX.Y.Z), update CHANGELOG.md
- **Never force-push to main**

### Credentials
All API credentials in Google Secret Manager (project: ai-agents-go).
Local service account key: `C:\Users\eukri\OneDrive\Documents\Claude Code\Credentials Claude Code\ai-agents-go-4c81b70995db.json`
Do NOT store credentials in code or commits.

### GCP Details
- **Project:** ai-agents-go
- **Region:** asia-southeast1
- **Service Account:** claude@ai-agents-go.iam.gserviceaccount.com

### Firestore Databases (this project reads from multiple)
| Database | Purpose | Access |
|---|---|---|
| `wechat-documents` (asia-southeast1) | Primary — wechat_files, wechat_products, wechat_contact_mapping, ingestion_log | Read/Write |
| `shipping-automation` (us-central1) | go_vendors, shipping_orders, shipping_contacts | Read only |
| `(default)` | people_contacts, peak_contacts, supplier_details | Read only |

### GCS Bucket
- `wechat-documents-attachments` (asia-southeast1) — uploaded vendor files

### Local Paths (Windows)
- WeChat auto-downloads: `C:\Users\eukri\OneDrive\Documents\xwechat_files\wxid_5i25oznpj6ox12_309f\msg\file\`
- WeChat manual downloads: `C:\Users\eukri\OneDrive\Documents\Documents GO\WeChat OneDrive\`
- WeChat images (encoded): `...\msg\attach\{hash}\{YYYY-MM}\Img\*.dat`

### Key Files
- `wechat_automation/models.py` — Pydantic models for all Firestore documents
- `wechat_automation/vendor_matcher.py` — Fuzzy vendor matching across 3 DBs
- `watcher/processor.py` — Main ingestion pipeline orchestrator
- `watcher/file_watcher.py` — watchdog-based local file watcher
- `scripts/initial_scan.py` — One-time backfill of all existing files
- `config/settings.py` — Environment-based configuration

### CI/CD
- Cloud Build trigger: `deploy-wechat-automation` on push to `main`
- Deploys MCP server to Cloud Run (asia-southeast1)
- Config: `cloudbuild.yaml`

---

## Claude Process Standards (MANDATORY)

Full reference: `Credentials Claude Code/Instructions/Claude Process Standards.md`

1. **Always maintain a todo list** — use `TodoWrite` for any task with >1 step or that edits files; mark items done immediately.
2. **Always update a build log** — append a dated, semver entry to `BUILD_LOG.md` (or existing `CHANGELOG.md`) for every build/version: version, date (YYYY-MM-DD), summary, files changed, outcome.
3. **Plan in batches; run them as one chained autonomous pass** — group todos into batches, surface the plan once, then execute every batch back-to-back in a single run. No turn-taking between todos or batches. Run long work with `run_in_background: true`; parallelize independent tool calls. Only stop for true blockers: destructive/unauthorized actions, missing credentials, genuine ambiguity, unrecoverable external errors, or explicit user confirmation request.
4. **Always update `build-summary.html`** at the project root for every build/version (template: `Credentials Claude Code/Instructions/build-summary.template.html`). Include version, date, status badge, and links to log + commit.
5. **Always commit and push — verify repo mapping first** — run `git remote -v` and confirm the remote repo name matches the local folder name (per the Code Sync Rules in the root `CLAUDE.md`). If mismatch (e.g. still pointing at `goco-project-template`), STOP and ask the user. Never push to the wrong repo.
