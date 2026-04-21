#!/bin/bash
# gitleaks-scan.sh — Run gitleaks on the project to catch committed secrets.
# Called from verify.sh. Fails the build on any finding.
#
# Usage: ./gitleaks-scan.sh [PROJECT_PATH]

set -e

PROJECT_PATH="${1:-$PWD}"
cd "$PROJECT_PATH"

if ! command -v gitleaks > /dev/null 2>&1; then
  echo "[WARN] gitleaks not installed. Install via:"
  echo "  winget install gitleaks.gitleaks   # Windows"
  echo "  brew install gitleaks              # Mac"
  echo "  Or: https://github.com/gitleaks/gitleaks/releases"
  echo "[SKIP] Skipping secret scan — install gitleaks and re-run verify.sh."
  exit 0
fi

echo "=== Gitleaks scan: $PROJECT_PATH ==="

# Working tree (catches uncommitted secrets too)
echo "--- Scanning working tree ---"
gitleaks detect --source . --no-git --exit-code 1 --redact --verbose || {
  echo ""
  echo "[FAIL] Gitleaks found secrets in the working tree. Fix before committing." >&2
  exit 1
}

# Full git history
echo ""
echo "--- Scanning full git history ---"
if [ -d ".git" ]; then
  gitleaks detect --source . --exit-code 1 --redact --verbose || {
    echo ""
    echo "[FAIL] Gitleaks found secrets in git history." >&2
    echo "       Rotate the exposed secret immediately, then purge from history:" >&2
    echo "       https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository" >&2
    exit 1
  }
fi

echo ""
echo "[OK] No secrets found"
