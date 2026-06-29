@echo off
cd /d "%~dp0"
.venv\Scripts\pip.exe install streamlit -q 2>nul
.venv\Scripts\streamlit.exe run dashboard.py --server.headless true
