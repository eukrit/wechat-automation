#!/usr/bin/env bash
# generate-hub-page.sh — Regenerate docs/hub.html (and docs/hub.live.html) per Rule 13.
#
# Usage:  ./generate-hub-page.sh [PROJECT_PATH]
#         Defaults to $PWD.
#
# Reads:
#   - hub.config.json at project root (LIVE_URL_BASE, hub.live.enabled, exclude, extra links)
#   - PROJECT_INDEX.md "User-Facing Dashboards & URLs" and "Relationships" sections
# Scans:
#   - *.html under docs/ (max 3 deep)
#   - The markdown essentials listed in Rule 13d (no PDFs/CSVs/arbitrary md)
# Emits:
#   - docs/hub.html              (always; relative links)
#   - docs/hub.live.html         (only when hub.live.enabled && LIVE_URL_BASE)
#
# Idempotent — byte-identical when inputs don't change.

set -euo pipefail

# Force UTF-8 for all python invocations — otherwise on Windows stdout defaults
# to cp1252 and em-dashes/non-ASCII characters in HTML <title> tags get garbled.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

PROJECT_PATH="${1:-$PWD}"
cd "$PROJECT_PATH"
PROJECT_NAME=$(basename "$PROJECT_PATH")

# Require docs/ per Rule 13a
[ -d docs ] || mkdir -p docs

CONFIG="hub.config.json"
EXCLUDE_PATTERNS=()
EXTRA_LINKS_JSON="[]"
LIVE_URL_BASE=""
HUB_LIVE_ENABLED="false"

if [ -f "$CONFIG" ]; then
  # Minimal JSON extraction via python (portable, no jq dep)
  LIVE_URL_BASE=$(python -c "import json,sys;d=json.load(open('$CONFIG'));print(d.get('LIVE_URL_BASE',''))" 2>/dev/null || echo "")
  HUB_LIVE_ENABLED=$(python -c "import json;d=json.load(open('$CONFIG'));print(str(d.get('hub',{}).get('live',{}).get('enabled',False)).lower())" 2>/dev/null || echo "false")
  # Exclude list joined by \n
  EXCLUDES=$(python -c "import json;d=json.load(open('$CONFIG'));print('\n'.join(d.get('hub',{}).get('exclude',[])))" 2>/dev/null || echo "")
  while IFS= read -r pat; do
    [ -n "$pat" ] && EXCLUDE_PATTERNS+=("$pat")
  done <<< "$EXCLUDES"
fi

TODAY=$(date +%Y-%m-%d)

# Classify an .html file path into a section id (essentials/dashboards/reports/forms/summaries/documents/catalogs/other).
classify() {
  local p="$1"
  case "$p" in
    docs/dashboards/*) echo "dashboards" ;;
    docs/reports/*)    echo "reports" ;;
    docs/forms/*)      echo "forms" ;;
    docs/summaries/*)  echo "summaries" ;;
    docs/documents/*)  echo "documents" ;;
    docs/catalogs/*)   echo "catalogs" ;;
    docs/build-summary.html) echo "essentials" ;;
    docs/index.html)   echo "dashboards" ;;
    docs/hub.html|docs/hub.live.html) echo "skip" ;;
    docs/*)            echo "other" ;;
    *)                 echo "other" ;;
  esac
}

is_excluded() {
  local p="$1"
  for pat in "${EXCLUDE_PATTERNS[@]:-}"; do
    [[ "$p" == $pat ]] && return 0
  done
  return 1
}

# Collect HTML rows
declare -A ROWS_BY_SECTION
ROWS_BY_SECTION[essentials]=""
ROWS_BY_SECTION[dashboards]=""
ROWS_BY_SECTION[reports]=""
ROWS_BY_SECTION[forms]=""
ROWS_BY_SECTION[summaries]=""
ROWS_BY_SECTION[documents]=""
ROWS_BY_SECTION[catalogs]=""
ROWS_BY_SECTION[other]=""

emit_row() {
  local section="$1" path="$2" href="$3"
  local mtime
  mtime=$(git log -1 --format=%cs -- "$path" 2>/dev/null || date -r "$path" +%Y-%m-%d 2>/dev/null || echo "")
  local fallback
  fallback=$(basename "$path" .html)
  local title
  title=$(HUB_TITLE_PATH="$path" HUB_TITLE_FALLBACK="$fallback" python - <<'PY' 2>/dev/null || echo "$fallback"
import os, re, sys, html as _html
p = os.environ["HUB_TITLE_PATH"]
fb = os.environ["HUB_TITLE_FALLBACK"]
try:
    with open(p, "r", encoding="utf-8", errors="ignore") as f:
        text = f.read(8000)
    m = re.search(r"<title>(.*?)</title>", text, re.I | re.S)
    title = m.group(1).strip() if m else fb
    title = _html.unescape(title)
    # Collapse whitespace and strip stray control chars
    title = re.sub(r"\s+", " ", title)
    sys.stdout.write(title)
except Exception:
    sys.stdout.write(fb)
PY
)
  # Escape HTML special chars in title for safe embedding
  title=$(HUB_RAW="$title" python - <<'PY'
import os, sys, html
sys.stdout.write(html.escape(os.environ.get("HUB_RAW", ""), quote=True))
PY
)
  local row="<tr><td><a href=\"${href}\">${title}</a></td><td><code>${path}</code></td><td>${mtime}</td></tr>"
  ROWS_BY_SECTION[$section]+="${row}"$'\n'
}

# Scan docs/ up to 3 deep for .html
while IFS= read -r -d '' f; do
  rel="${f#./}"
  is_excluded "$rel" && continue
  section=$(classify "$rel")
  [ "$section" = "skip" ] && continue
  emit_row "$section" "$rel" "../$rel"   # Hub lives at docs/hub.html, so docs-relative paths prefix with ../ won't be right
done < <(find docs -maxdepth 3 -type f -name "*.html" -print0 2>/dev/null)

# Wait — docs/hub.html links to other docs/* files, so relative path is just the tail after docs/
# Rebuild ROWS using correct relative paths for local hub:
for k in "${!ROWS_BY_SECTION[@]}"; do ROWS_BY_SECTION[$k]=""; done
while IFS= read -r -d '' f; do
  rel="${f#./}"
  is_excluded "$rel" && continue
  section=$(classify "$rel")
  [ "$section" = "skip" ] && continue
  rel_from_hub="${rel#docs/}"
  emit_row "$section" "$rel" "$rel_from_hub"
done < <(find docs -maxdepth 3 -type f -name "*.html" -print0 2>/dev/null)

# Essentials markdown — referenced from the Local hub only (hub.live.html omits PROGRESS.md)
ESSENTIALS_MD_ROWS=""
add_md() {
  local path="$1" label="$2"
  [ -f "$path" ] || return 0
  local mtime
  mtime=$(git log -1 --format=%cs -- "$path" 2>/dev/null || date -r "$path" +%Y-%m-%d 2>/dev/null || echo "")
  # Local hub lives at docs/hub.html → link is ../<path>
  ESSENTIALS_MD_ROWS+="<tr><td><a href=\"../${path}\">${label}</a></td><td><code>${path}</code></td><td>${mtime}</td></tr>"$'\n'
}
add_md "PROJECT_INDEX.md" "Project Index"
add_md "BUILD_LOG.md"     "Build Log"
add_md "CHANGELOG.md"     "Changelog"
add_md "SECURITY.md"      "Security Surface"
add_md "COLLABORATORS.md" "Collaborators & Access"
add_md ".claude/PROGRESS.md" "Progress (local)"

# Live URLs — parsed from PROJECT_INDEX.md "User-Facing Dashboards & URLs" block
LIVE_URL_ROWS=""
if [ -f "PROJECT_INDEX.md" ]; then
  LIVE_URL_ROWS=$(python - <<'PY'
import re,sys
try:
    text=open("PROJECT_INDEX.md","r",encoding="utf-8").read()
except Exception:
    print("");sys.exit(0)
m=re.search(r'## User-Facing Dashboards & URLs(.*?)(?=^## |\Z)',text,re.S|re.M)
if not m:
    print(""); sys.exit(0)
rows=[]
for line in m.group(1).splitlines():
    line=line.strip()
    if not line.startswith("- "): continue
    body=line[2:]
    # Pull the first URL if present
    u=re.search(r'https?://\S+',body)
    label=body.split(":")[0] if ":" in body else body[:60]
    if u:
        rows.append(f'<tr><td>{label}</td><td><a href="{u.group(0)}">{u.group(0)}</a></td></tr>')
print("\n".join(rows))
PY
)
fi

# Related projects
RELATED_ROWS=""
if [ -f "PROJECT_INDEX.md" ]; then
  RELATED_ROWS=$(python - <<'PY'
import re,sys
try:
    text=open("PROJECT_INDEX.md","r",encoding="utf-8").read()
except Exception:
    print(""); sys.exit(0)
m=re.search(r'## Relationships(.*?)(?=^## |\Z)',text,re.S|re.M)
if not m:
    print(""); sys.exit(0)
rows=[]
for line in m.group(1).splitlines():
    line=line.strip()
    if not line.startswith("- "): continue
    # Extract project names from "- **Depends on:** proj-a, proj-b"
    body=line[2:]
    m2=re.match(r'\*\*(Depends on|Depended on by)\*\*:\s*(.*)',body)
    if not m2: continue
    direction=m2.group(1)
    for name in [n.strip() for n in m2.group(2).split(",") if n.strip() and n.strip() != "[other projects]"]:
        rows.append(f'<tr><td>{direction}</td><td>{name}</td><td><a href="https://github.com/eukrit/{name}">repo</a></td></tr>')
print("\n".join(rows))
PY
)
fi

# Emit a section block only if it has rows
section_block() {
  local title="$1" rows="$2" headers="$3"
  if [ -n "$rows" ]; then
    cat <<SEC
  <h2>${title}</h2>
  <table>
    <thead><tr>${headers}</tr></thead>
    <tbody>
${rows}    </tbody>
  </table>
SEC
  fi
}

# CSS/header shared by both variants
HEAD_CSS='<style>
  body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#1a1a1a}
  h1{margin-bottom:.25rem}
  h2{margin-top:2rem;border-bottom:1px solid #eee;padding-bottom:4px}
  .meta{color:#666;font-size:.9rem;margin-bottom:1.5rem}
  .toggle{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;padding:.5rem 1rem;margin-bottom:1rem;font-size:.9rem}
  table{width:100%;border-collapse:collapse;margin-top:.5rem}
  th,td{text-align:left;padding:8px 12px;border-bottom:1px solid #eee;vertical-align:top}
  th{background:#fafafa;font-weight:600}
  code{background:#f4f4f5;padding:1px 6px;border-radius:4px;font-size:.9em}
  a{color:#2563eb;text-decoration:none}
  a:hover{text-decoration:underline}
</style>'

write_hub() {
  local out="$1" variant="$2" toggle_html="$3" url_prefix="$4"
  {
    cat <<HEAD
<!doctype html>
<html lang="en"><head><meta charset="utf-8"/>
<title>${PROJECT_NAME} — Hub Page ${variant}</title>
${HEAD_CSS}
</head><body>
<h1>${PROJECT_NAME} <span style="font-weight:400;color:#666">— Hub Page ${variant}</span></h1>
<div class="meta">Generated ${TODAY} · See <a href="../PROJECT_INDEX.md">PROJECT_INDEX.md</a> · Rule 13</div>
${toggle_html}
HEAD
    section_block "Project essentials" "${ESSENTIALS_MD_ROWS}${ROWS_BY_SECTION[essentials]}" "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Dashboards"         "${ROWS_BY_SECTION[dashboards]}" "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Reports"            "${ROWS_BY_SECTION[reports]}"    "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Forms"              "${ROWS_BY_SECTION[forms]}"      "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Summaries"          "${ROWS_BY_SECTION[summaries]}"  "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Documents"          "${ROWS_BY_SECTION[documents]}"  "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Catalogs"           "${ROWS_BY_SECTION[catalogs]}"   "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Other HTML"         "${ROWS_BY_SECTION[other]}"      "<th>Title</th><th>Path</th><th>Updated</th>"
    section_block "Live URLs"          "${LIVE_URL_ROWS}"               "<th>Name</th><th>URL</th>"
    section_block "Related projects"   "${RELATED_ROWS}"                "<th>Direction</th><th>Project</th><th>Link</th>"
    cat <<FOOT
<p class="meta">Regenerated by <code>scripts/generate-hub-page.sh</code>. Do not edit by hand — edit <code>hub.config.json</code> or the source sub-pages.</p>
</body></html>
FOOT
  } > "$out"
}

# Local hub
TOGGLE_LOCAL=""
if [ "$HUB_LIVE_ENABLED" = "true" ] && [ -n "$LIVE_URL_BASE" ]; then
  TOGGLE_LOCAL="<div class=\"toggle\">Viewing <strong>Hub Page Local</strong> · <a href=\"${LIVE_URL_BASE%/}/hub\">View Hub Page Live →</a></div>"
fi
write_hub "docs/hub.html" "Local" "$TOGGLE_LOCAL" ""

echo "[OK] docs/hub.html regenerated ($(wc -l < docs/hub.html) lines)"

# Live hub — rewrite relative hrefs to absolute using LIVE_URL_BASE
if [ "$HUB_LIVE_ENABLED" = "true" ] && [ -n "$LIVE_URL_BASE" ]; then
  BASE="${LIVE_URL_BASE%/}"
  # Rebuild rows with absolute URLs for sub-pages
  for k in "${!ROWS_BY_SECTION[@]}"; do ROWS_BY_SECTION[$k]=""; done
  while IFS= read -r -d '' f; do
    rel="${f#./}"
    is_excluded "$rel" && continue
    section=$(classify "$rel")
    [ "$section" = "skip" ] && continue
    rel_from_hub="${rel#docs/}"
    emit_row "$section" "$rel" "${BASE}/${rel_from_hub}"
  done < <(find docs -maxdepth 3 -type f -name "*.html" -print0 2>/dev/null)
  # Essentials — link to GitHub blob URLs for markdown
  ESSENTIALS_MD_ROWS=""
  REPO_URL=$(git config --get remote.origin.url 2>/dev/null | sed -E 's|git@github.com:|https://github.com/|; s|\.git$||' || echo "")
  BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "main")
  add_md_abs() {
    local path="$1" label="$2"
    [ -f "$path" ] || return 0
    local mtime
    mtime=$(git log -1 --format=%cs -- "$path" 2>/dev/null || echo "")
    local url="${REPO_URL}/blob/${BRANCH}/${path}"
    ESSENTIALS_MD_ROWS+="<tr><td><a href=\"${url}\">${label}</a></td><td><code>${path}</code></td><td>${mtime}</td></tr>"$'\n'
  }
  add_md_abs "PROJECT_INDEX.md" "Project Index"
  add_md_abs "BUILD_LOG.md"     "Build Log"
  add_md_abs "CHANGELOG.md"     "Changelog"
  add_md_abs "SECURITY.md"      "Security Surface"
  add_md_abs "COLLABORATORS.md" "Collaborators & Access"
  TOGGLE_LIVE="<div class=\"toggle\">Viewing <strong>Hub Page Live</strong> · <a href=\"hub.html\">← View Hub Page Local</a></div>"
  write_hub "docs/hub.live.html" "Live" "$TOGGLE_LIVE" "$BASE"
  echo "[OK] docs/hub.live.html regenerated ($(wc -l < docs/hub.live.html) lines)"
fi
