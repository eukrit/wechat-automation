#!/bin/bash
# apply-branch-protection.sh — Apply Process Standards Rule 11 branch protection to a GitHub repo's main branch.
# Idempotent; safe to re-run.
#
# Usage: ./apply-branch-protection.sh eukrit/<repo-name> [main|master]
#
# Requires: `gh` CLI authenticated with repo admin access.

set -e

REPO="${1:?Usage: ./apply-branch-protection.sh eukrit/<repo> [branch]}"
BRANCH="${2:-main}"

echo "=== Applying branch protection to $REPO ($BRANCH) ==="

# Verify gh is authenticated
if ! gh auth status > /dev/null 2>&1; then
  echo "[ERROR] gh is not authenticated. Run 'gh auth login' first." >&2
  exit 1
fi

# Check repo exists and we have admin access
if ! gh api "repos/$REPO" > /dev/null 2>&1; then
  echo "[ERROR] Repo $REPO not found or no access." >&2
  exit 1
fi

# Apply the standard protection rules
# Policy: admin (repo owner) CAN push directly; collaborators MUST go through PR.
# Rationale: on personal-account repos, admins can always toggle protection off to push
# anyway, so the bypass adds friction without real security. Instead we leave
# enforce_admins=false, which lets the owner push directly and keeps the audit
# trail clean. Collaborators are still gated by PR + CODEOWNERS + linear history.
#
# - Require PR with 1 approval (for non-admins)
# - Require CODEOWNERS review
# - Require last push approval (blocks self-approving your own pushed commits)
# - Dismiss stale approvals on new push
# - Require linear history (no merge commits from non-PR flows)
# - Require conversation resolution
# - Block force pushes and deletions
# - enforce_admins = false (owner bypass permitted)
gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" \
  --input - <<'EOF'
{
  "required_status_checks": null,
  "enforce_admins": false,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "require_last_push_approval": true
  },
  "restrictions": null,
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "block_creations": false,
  "required_conversation_resolution": true,
  "lock_branch": false,
  "allow_fork_syncing": false
}
EOF

echo "[OK] Branch protection applied to $REPO:$BRANCH"

# Verify
echo ""
echo "--- Current protection ---"
gh api "repos/$REPO/branches/$BRANCH/protection" \
  --jq '{
    enforce_admins: .enforce_admins.enabled,
    require_pr: .required_pull_request_reviews.required_approving_review_count,
    codeowners: .required_pull_request_reviews.require_code_owner_reviews,
    dismiss_stale: .required_pull_request_reviews.dismiss_stale_reviews,
    force_push: .allow_force_pushes.enabled,
    deletions: .allow_deletions.enabled,
    conversation_resolution: .required_conversation_resolution.enabled
  }'

echo ""
echo "[OK] Done"
