@echo off
rem Double-click to open Niche Finder (Windows). Needs Python 3 from python.org.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 tools\niche_app.py) else (python tools\niche_app.py)
pause
