# Security — wechat-automation
_Last updated: 2026-04-22_

> Per-project threat model and onboarding security checklist. Read this before granting access to anyone.

## Threat Model

### What this project's pipeline can do (if compromised)
- [e.g. "Read and send email as any goco.bz user via DWD on `gmail-service-account`"]
- [e.g. "Read and write the `shipping-automation` Firestore DB"]
- [e.g. "Post to Slack `#shipping-alerts`"]
- [e.g. "Deploy arbitrary code to Cloud Run service `shipping-automation`"]

### High-privilege identities
| Identity | Type | Powers | Lives in |
| --- | --- | --- | --- |
| `claude@ai-agents-go.iam.gserviceaccount.com` | Service Account | Reads all SM secrets this project uses, writes Firestore, deploys Cloud Run | GCP IAM |
| `[gmail-service-account]@ai-agents-go.iam.gserviceaccount.com` | Service Account with DWD | Impersonates any goco.bz user (reads/sends any mailbox) | GCP IAM + Workspace Admin Console |
| `538978391890-compute@developer.gserviceaccount.com` | Compute SA | Default Cloud Build runtime | GCP IAM |

### Hot secrets (GCP Secret Manager)
| Secret | Backs identity | Rotation cadence |
| --- | --- | --- |
| `[gmail-service-account]` | DWD SA above | Annual, or on any suspected exposure |
| `[xero-refresh-token]` | Xero OAuth | Rotates on every use (automatic) |
| `[peak-user-token]` | Peak API auth | Annual |

## Onboarding Checklist (before granting access to any new collaborator)

### 1. Repo hygiene
- [ ] Run `gitleaks detect --source . --no-git` → exit 0, no findings
- [ ] Run `gitleaks detect --source .` (full history) → exit 0, no findings
- [ ] `git ls-files | grep -E '(\.env$|credentials/|_tokens\.json|client_secret_|\.key$|\.pem$)'` → empty
- [ ] `.gitignore` blocks all credential patterns (inherited from template)

### 2. GCP IAM
- [ ] Grant ONLY the conditioned bindings needed for the role (see COLLABORATORS.md template)
- [ ] Explicitly confirm NO `secretmanager.secretAccessor` on hot secrets above
- [ ] Explicitly confirm NO `iam.serviceAccountUser` / `serviceAccountTokenCreator` on high-privilege SAs
- [ ] Use `resource.name == "projects/ai-agents-go/databases/[db]"` conditions for Firestore — never grant project-wide `datastore.*`

### 3. GitHub
- [ ] Branch protection on `main`: applied via `apply-branch-protection.sh eukrit/wechat-automation`
- [ ] `.github/CODEOWNERS` present with owner required on deploy-surface paths
- [ ] Collaborator role: Write (gated by branch protection) or Read (stricter)
- [ ] No org-level permissions bypass (N/A for personal-account repos)

### 4. Google Workspace
- [ ] New user has NO admin role (Super, User Management, Groups, Help Desk, custom)
- [ ] NOT listed as a delegate on any other goco.bz mailbox (check Admin Console → Users → [user] → Data → Gmail delegation)
- [ ] NO "Send mail as" address other than their own

### 5. Post-grant verification
- [ ] As the new user, test the intended access works (e.g. Firestore read via console)
- [ ] As the new user, test each denied path fails with `PERMISSION_DENIED`
- [ ] `gcloud projects get-iam-policy ai-agents-go --flatten=bindings --filter="bindings.members:[email]"` matches expected bindings exactly
- [ ] Update [COLLABORATORS.md](COLLABORATORS.md) with the grant

## Offboarding Checklist (when revoking access)
- [ ] Remove all GCP IAM bindings: `gcloud projects remove-iam-policy-binding ai-agents-go --member="user:[email]" --role="[role]"`
- [ ] Remove GitHub collaborator: `gh api -X DELETE repos/eukrit/wechat-automation/collaborators/[username]`
- [ ] Remove Workspace mailbox delegation (if any)
- [ ] Rotate any secret the user had access to (defensive)
- [ ] Move their entry in COLLABORATORS.md from "Active" to "Removed" with date + reason

## Incident Response
If a secret is suspected compromised:
1. Rotate immediately: `gcloud secrets versions add <name> --data-file=-` with new value
2. Disable the old version: `gcloud secrets versions disable <old-version> --secret=<name>`
3. Redeploy Cloud Run so the new value is picked up
4. Audit access logs: `gcloud logging read 'resource.type="secretmanager.googleapis.com/Secret" AND resource.labels.secret_id="<name>"' --limit 100 --project=ai-agents-go`
5. Document in [BUILD_LOG.md](BUILD_LOG.md) or incident log

## References
- Workspace SOP: `Credentials Claude Code/Instructions/Collaborator Access SOP.md`
- Process Standards Rule 11
- [COLLABORATORS.md](COLLABORATORS.md) — who has what access
- [PROJECT_INDEX.md](PROJECT_INDEX.md) — Security Surface section
