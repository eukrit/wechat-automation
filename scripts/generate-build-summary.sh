#!/bin/bash
# generate-build-summary.sh — Regenerate build-summary.html from BUILD_LOG.md (or CHANGELOG.md)
# Called from verify.sh after tests pass. Idempotent.
#
# Usage: ./generate-build-summary.sh [PROJECT_PATH]
#   Defaults to current directory.

set -e

PROJECT_PATH="${1:-$PWD}"
cd "$PROJECT_PATH"

# Figure out project name from the folder or package.json
PROJECT_NAME=$(basename "$PROJECT_PATH")
if [ -f "package.json" ]; then
  PROJECT_NAME=$(grep -oP '"name"\s*:\s*"\K[^"]+' package.json | head -1 || echo "$PROJECT_NAME")
fi

# Pick the log file
LOG_FILE=""
if [ -f "BUILD_LOG.md" ]; then
  LOG_FILE="BUILD_LOG.md"
elif [ -f "CHANGELOG.md" ]; then
  LOG_FILE="CHANGELOG.md"
else
  echo "[ERROR] No BUILD_LOG.md or CHANGELOG.md found in $PROJECT_PATH" >&2
  exit 1
fi

# Get repo URL + branch + commit
REPO_URL=$(git config --get remote.origin.url 2>/dev/null | sed -E 's|git@github.com:|https://github.com/|; s|\.git$||' || echo "")
BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
COMMIT_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
COMMIT_URL=""
if [ -n "$REPO_URL" ]; then
  COMMIT_URL="$REPO_URL/commit/$(git rev-parse HEAD 2>/dev/null || echo '')"
fi
TODAY=$(date +%Y-%m-%d)

# Parse BUILD_LOG.md entries. Each version entry is expected to match:
#   ## [1.4.2] - 2026-04-22 (semver + date)
#   or  ## 1.4.2 - 2026-04-22
#   or  ## v1.4.2 - 2026-04-22
# followed by a summary line and optional bullet lines. Status inferred from keywords.

ROWS=""
LATEST_VERSION=""
LATEST_DATE=""
LATEST_SUMMARY=""
LATEST_STATUS="pending"

while IFS= read -r line; do
  if [[ "$line" =~ ^##[[:space:]]+\[?v?([0-9]+\.[0-9]+\.[0-9]+)\]?[[:space:]]+-[[:space:]]+([0-9]{4}-[0-9]{2}-[0-9]{2}) ]]; then
    VER="${BASH_REMATCH[1]}"
    DATE="${BASH_REMATCH[2]}"
    SUMMARY=""
    STATUS="success"
  elif [[ -n "$VER" && -z "$SUMMARY" && -n "$line" && ! "$line" =~ ^## ]]; then
    # First non-empty line after the header = summary
    SUMMARY=$(echo "$line" | sed 's/^[-*[:space:]]*//' | head -c 200)
    # Infer status
    if echo "$line" | grep -qiE '(fail|revert|rollback|broken)'; then
      STATUS="failed"
    elif echo "$line" | grep -qiE '(pending|in-progress|wip)'; then
      STATUS="pending"
    else
      STATUS="success"
    fi
    # Emit a row
    BADGE_CLASS="badge-$STATUS"
    ROW=$(printf '      <tr><td><code>%s</code></td><td>%s</td><td>%s</td><td><span class="badge %s">%s</span></td></tr>' \
      "$VER" "$DATE" "$SUMMARY" "$BADGE_CLASS" "$STATUS")
    ROWS="$ROWS$ROW"$'\n'
    # Track latest
    if [ -z "$LATEST_VERSION" ]; then
      LATEST_VERSION="$VER"
      LATEST_DATE="$DATE"
      LATEST_SUMMARY="$SUMMARY"
      LATEST_STATUS="$STATUS"
    fi
    # Reset for next block
    VER=""
  fi
done < "$LOG_FILE"

# Fallback if parsing produced nothing
if [ -z "$LATEST_VERSION" ]; then
  LATEST_VERSION="0.1.0"
  LATEST_DATE="$TODAY"
  LATEST_SUMMARY="(No parsed entries — check $LOG_FILE format)"
  LATEST_STATUS="pending"
  ROWS=$(printf '      <tr><td colspan="4">No versions parsed from %s</td></tr>' "$LOG_FILE")
fi

BADGE_CLASS="badge-$LATEST_STATUS"

mkdir -p docs
OUTPUT_PATH="docs/build-summary.html"
# Backwards compatibility: if a legacy root build-summary.html exists from a pre-Rule-13
# build, remove it once we've written the new location (Rule 13 requires docs-only layout).
LEGACY_PATH="build-summary.html"
cat > "$OUTPUT_PATH" <<HTMLEOF
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>$PROJECT_NAME — Build Summary</title>
  <style>
    body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 960px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
    h1 { margin-bottom: 0.25rem; }
    h2 { margin-top: 2rem; border-bottom: 1px solid #eee; padding-bottom: 4px; }
    .meta { color: #666; font-size: 0.9rem; margin-bottom: 1.5rem; }
    .badge { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; }
    .badge-success { background: #d1fae5; color: #065f46; }
    .badge-failed  { background: #fee2e2; color: #991b1b; }
    .badge-pending { background: #fef3c7; color: #92400e; }
    table { width: 100%; border-collapse: collapse; margin-top: 0.5rem; }
    th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #eee; vertical-align: top; }
    th { background: #fafafa; font-weight: 600; }
    code { background: #f4f4f5; padding: 1px 6px; border-radius: 4px; font-size: 0.9em; }
    a { color: #2563eb; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .latest-card { background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 1rem 1.25rem; }
  </style>
</head>
<body>
  <h1>$PROJECT_NAME</h1>
  <div class="meta">
    Repo: <a href="$REPO_URL">$REPO_URL</a> ·
    Branch: <code>$BRANCH</code> ·
    Generated: $TODAY
  </div>

  <div class="latest-card">
    <h2 style="margin-top:0;border:0">Latest build</h2>
    <p>
      Version <strong>$LATEST_VERSION</strong> &middot; $LATEST_DATE &middot;
      <span class="badge $BADGE_CLASS">$LATEST_STATUS</span>
    </p>
    <p>$LATEST_SUMMARY</p>
    <p>
      <a href="$LOG_FILE">Full build log</a> &middot;
      <a href="$COMMIT_URL">Commit $COMMIT_SHA</a> &middot;
      <a href="PROJECT_INDEX.md">Project index</a>
    </p>
  </div>

  <h2>All versions</h2>
  <table>
    <thead><tr><th>Version</th><th>Date</th><th>Summary</th><th>Status</th></tr></thead>
    <tbody>
$ROWS
    </tbody>
  </table>

  <p class="meta">Generated by <code>scripts/generate-build-summary.sh</code> from <code>$LOG_FILE</code>.</p>
</body>
</html>
HTMLEOF

if [ -f "$LEGACY_PATH" ]; then
  rm "$LEGACY_PATH"
  echo "[CLEANUP] removed legacy $LEGACY_PATH (Rule 13 — build-summary lives in docs/)"
fi
echo "[OK] $OUTPUT_PATH regenerated ($(wc -l < "$OUTPUT_PATH") lines)"
