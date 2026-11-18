@echo off
title cocbot - avvio debug
cd /d "%~dp0"
echo Avvio GUI cocbot (questa finestra mostra gli errori)...
echo.
python -m cocbot gui
echo.
echo La GUI e' terminata (exit %errorlevel%).
pause
