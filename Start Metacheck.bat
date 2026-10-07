@echo off
rem Launch the ManuscriptChecker desktop app (no console window).
set "DIR=%~dp0"
set "PYW=%DIR%.venv\Scripts\pythonw.exe"
if not exist "%PYW%" set "PYW=pythonw"
start "" "%PYW%" "%DIR%metacheck_gui.py"
