# WeChat Automation — Claude Code Instructions

> **Session start protocol (Rule 6):** read `.claude/PROGRESS.md` and `PROJECT_INDEX.md` before making changes. Check `COLLABORATORS.md` and `SECURITY.md` before granting access. Update `.claude/PROGRESS.md` before ending any turn that edited code.

> **Primary GCP project: `ai-agents-go`** (538978391890, region `asia-southeast1`). Do NOT use `ai-agents-eukrit` — that project is reserved for the `2026 Eukrit Expenses Claude/` folder only.

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
Local service account key: `C:\Users\eukri\OneDrive\Documents\Claude Code\Credentials Claude Code\ai-agents-go-0d28f3991b7b.json`
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

## Page Hosting (Rule 14)

> **Rule 14a — Exclusive hosting.** All generated non-website HTML for this project (dashboards, reports, summaries, forms, documents, hub, build-summary, architecture) is served exclusively at `https://gateway.goco.bz/wechat-automation/<path>`. Do not link, share, or reference raw `*.run.app`, `storage.googleapis.com`, `raw.githubusercontent.com`, or `eukrit.github.io` URLs anywhere a reader will see (BUILD_LOGs, hub configs, READMEs, chat).
>
> **Rule 14b — Project root = hub.** `https://gateway.goco.bz/wechat-automation/` (and `https://gateway.goco.bz/wechat-automation` with no slash) resolves to this project's `docs/hub.html` for every backend kind. The slug catchall in `go-access-gateway/services/access_gateway/routes/pages.py` normalizes the empty path. Keep `docs/hub.html` fresh per Rule 13f — `verify.sh` blocks any push that leaves it stale.
>
> **Canonical paths** (must always work, mirroring `gateway.goco.bz/directory`):
> - `https://gateway.goco.bz/wechat-automation/docs/hub.html` — Hub
> - `https://gateway.goco.bz/wechat-automation/docs/build-summary.html` — Build Summary
> - `https://gateway.goco.bz/wechat-automation/docs/architecture.html` — Architecture
> - `https://gateway.goco.bz/wechat-automation/BUILD_LOG.md` — Build Log

All HTML pages, dashboards, summaries, and forms in this project are served via the **`go-access-gateway`** at `https://gateway.goco.bz/wechat-automation/...` — NOT directly from this project's Cloud Run URL.

- **Public URL pattern:** `https://gateway.goco.bz/wechat-automation/<path>`
- **Backend Cloud Run service:** must be `--no-allow-unauthenticated`. The gateway SA `claude@ai-agents-go.iam.gserviceaccount.com` is granted `roles/run.invoker` on this service.
- **Default page visibility:** `admin` (only `eukrit@goco.bz`). Toggle public, or share with specific emails, via the [gateway admin UI](https://gateway.goco.bz/admin).
- **Hub link target:** `hub.config.json` `LIVE_URL_BASE` should be `https://gateway.goco.bz/wechat-automation`.
- **Migration status:** see Phase D of the rollout plan at `~/.claude/plans/go-through-all-projects-structured-cherny.md`. Until migrated, this project's Cloud Run is still public.

Hard rules: no `--allow-unauthenticated` on this project's Cloud Run after migration. No public GCS buckets for HTML. No bypass auth in the backend. Full text: Rule 14 in `Credentials Claude Code/Instructions/Claude Process Standards.md`.

## Claude Process Standards (MANDATORY)

Full reference: `Credentials Claude Code/Instructions/Claude Process Standards.md`

0. **`goco-project-template` is READ-ONLY** — never edit, commit, or push to the `goco-project-template` folder or `eukrit/goco-project-template` repo. It exists only to be copied when scaffolding new projects. If any project's `origin` points at `goco-project-template`, STOP and remove/fix the remote before doing anything else.
1. **Always maintain a todo list** — use `TodoWrite` for any task with >1 step or that edits files; mark items done immediately.
2. **Always update a build log** — append a dated, semver entry to `BUILD_LOG.md` (or existing `CHANGELOG.md`) for every build/version: version, date (YYYY-MM-DD), summary, files changed, outcome. The log lives in **this project's own folder** — never in `business-automation/`.
3. **Plan in batches; run them as one chained autonomous pass** — group todos into batches, surface the plan once, then execute every batch back-to-back in a single run. No turn-taking between todos or batches. Run long work with `run_in_background: true`; parallelize independent tool calls. Only stop for true blockers: destructive/unauthorized actions, missing credentials, genuine ambiguity, unrecoverable external errors, or explicit user confirmation request.
4. **Always update `docs/build-summary.html` at THIS project's root** for every build/version (template: `Credentials Claude Code/Instructions/build-summary.template.html`). Per-project — DO NOT write into `business-automation/`. Touch the workspace dashboard at `business-automation/docs/index.html` only for cross-project / architecture changes.
5. **Always commit and push — verify repo mapping first** — run `git remote -v` and confirm the remote repo name matches the local folder name (per the Code Sync Rules in the root `CLAUDE.md`). If mismatch (especially `goco-project-template`), STOP and ask the user. Never push to the wrong repo.

## Page Hosting (Rule 14)

> **Rule 14a — Exclusive hosting.** All generated non-website HTML for this project (dashboards, reports, summaries, forms, documents, hub, build-summary, architecture) is served exclusively at `https://gateway.goco.bz/wechat-automation/<path>`. Do not link, share, or reference raw `*.run.app`, `storage.googleapis.com`, `raw.githubusercontent.com`, or `eukrit.github.io` URLs anywhere a reader will see (BUILD_LOGs, hub configs, READMEs, chat).
>
> **Rule 14b — Project root = hub.** `https://gateway.goco.bz/wechat-automation/` (and `https://gateway.goco.bz/wechat-automation` with no slash) resolves to this project's `docs/hub.html` for every backend kind. The slug catchall in `go-access-gateway/services/access_gateway/routes/pages.py` normalizes the empty path. Keep `docs/hub.html` fresh per Rule 13f — `verify.sh` blocks any push that leaves it stale.
>
> **Canonical paths** (must always work, mirroring `gateway.goco.bz/directory`):
> - `https://gateway.goco.bz/wechat-automation/docs/hub.html` — Hub
> - `https://gateway.goco.bz/wechat-automation/docs/build-summary.html` — Build Summary
> - `https://gateway.goco.bz/wechat-automation/docs/architecture.html` — Architecture
> - `https://gateway.goco.bz/wechat-automation/BUILD_LOG.md` — Build Log

