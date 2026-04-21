# Collaborators — wechat-automation
_Last updated: 2026-04-22_

> Canonical ledger of every person with any access to this project (GCP IAM, GitHub, Google Workspace, shared mailboxes). Updated on grant, modify, revoke. Reviewed quarterly.

## Owner
- **Eukrit Seang** <eukrit@goco.bz>
  - GCP: Project Owner on `ai-agents-go`
  - GitHub: Owner of `eukrit/wechat-automation`
  - Workspace: goco.bz admin

## Active Collaborators

<!-- Template for each collaborator — duplicate this block when onboarding someone new.

### [Name] <[email@goco.bz]>
- **Added:** [YYYY-MM-DD] by [approver]
- **Role:** [Developer | Reviewer | Read-only]
- **Scope:**
  - **GCP:**
    - `roles/datastore.viewer` on `projects/ai-agents-go/databases/[db-name]` (conditioned: `resource.name == "projects/ai-agents-go/databases/[db-name]"`)
    - `roles/firebase.viewer` (project-wide, read-only console)
    - [other conditioned bindings]
  - **GitHub:** Write on `eukrit/wechat-automation` (branch protection on `main` gates all merges)
  - **Workspace:** Standard user, no admin roles
  - **Shared mailboxes:** [none | list with `delegate` or `member` scope]
- **Explicitly DENIED:**
  - `roles/secretmanager.secretAccessor` on ANY secret
  - `roles/iam.serviceAccountUser` on `claude@ai-agents-go.iam.gserviceaccount.com`
  - `roles/iam.serviceAccountTokenCreator` on any SA
  - Domain-Wide Delegation impersonation of any user
  - Direct push to `main` (branch protection enforces)
- **Reviewed:** [YYYY-MM-DD] by [reviewer]
- **Review cadence:** quarterly
-->

## Removed Collaborators (audit trail)

<!-- Keep historical entries when access is revoked.

### [Name] <[email]>
- **Added:** [YYYY-MM-DD] · **Removed:** [YYYY-MM-DD] by [approver]
- **Reason:** [offboarded | scope change | policy]
- **Scope when active:** [summary]
-->

## Policy References
- Workspace SOP: `Credentials Claude Code/Instructions/Collaborator Access SOP.md`
- Process Standards Rule 11 (Safe-by-default collaboration)
- Per-project threat model: [SECURITY.md](SECURITY.md)
