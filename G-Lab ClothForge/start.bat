@echo off
cd /d "%~dp0"
python cloth_tool.py %*
if errorlevel 1 pause
