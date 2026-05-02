@echo off
REM Requires GOOGLE_APPLICATION_CREDENTIALS set in your environment (load via .env
REM or `gcloud auth application-default login`). Per workspace SOP Rule 12b, no
REM hardcoded SA-key filenames in code.
if not defined GOOGLE_APPLICATION_CREDENTIALS (
  echo ERROR: GOOGLE_APPLICATION_CREDENTIALS is not set. 1>&2
  echo Set it in your .env or run: gcloud auth application-default login 1>&2
  exit /b 1
)
cd /d "C:\Users\eukri\OneDrive\Documents\Claude Code\wechat-automation"
python -m watcher.file_watcher
