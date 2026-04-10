@echo off
REM WeChat File Watcher — started by Task Scheduler on login
set GOOGLE_APPLICATION_CREDENTIALS=C:\Users\eukri\OneDrive\Documents\Claude Code\Credentials Claude Code\ai-agents-go-4c81b70995db.json
cd /d "C:\Users\eukri\OneDrive\Documents\Claude Code\wechat-automation"
python -m watcher.file_watcher
