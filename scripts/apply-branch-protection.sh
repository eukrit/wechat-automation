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
# - Require PR with 1 approval
# - Require CODEOWNERS review
# - Dismiss stale approvals on new push
# - Require conversation resolution
# - Block force pushes and deletions
# - Enforce on admins (owner included)
# - Do not allow bypass
gh api -X PUT "repos/$REPO/branches/$BRANCH/protection" \
  --input - <<'EOF'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": true,
    "require_last_push_approval": false
  },
  "restrictions": null,
  "required_linear_history": false,
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
