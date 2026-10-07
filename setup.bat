@echo off
rem One-time setup for the ManuscriptChecker desktop app on a target PC.
rem Run once after copying the folder. Then double-click ManuscriptChecker.exe.

set "DIR=%~dp0"
echo === ManuscriptChecker setup ===

set "RSCRIPT="
for /f "delims=" %%i in ('where Rscript 2^>nul') do if not defined RSCRIPT set "RSCRIPT=%%i"
if not defined RSCRIPT (
  for /f "delims=" %%i in ('dir /b /s "C:\Program Files\R\R-*\bin\Rscript.exe" 2^>nul') do if not defined RSCRIPT set "RSCRIPT=%%i"
)
if not defined RSCRIPT (
  echo [ERROR] Rscript not found.
  echo         Install R from https://cran.r-project.org/ and retry.
  echo         metacheck needs R ^+ the metacheck package to run its checks.
) else (
  echo [OK] Rscript: %RSCRIPT%
  echo Installing / checking the metacheck R package...
  "%RSCRIPT%" "%DIR%scripts\setup_r.R"
)

where soffice >nul 2>nul
if errorlevel 1 (
  echo [WARN] LibreOffice not found. DOCX/DOC/HTML conversion needs it; PDFs work without it.
) else (
  echo [OK] LibreOffice found.
)

echo.
echo Setup complete. Double-click ManuscriptChecker.exe to start.
pause
