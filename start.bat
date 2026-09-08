@echo off
chcp 65001 >nul
title Quote Bot
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1
echo.
echo   ربات در حال روشن شدن...
echo   براي خاموش کردن، همين پنجره را ببنديد يا Ctrl+C بزنيد.
echo.
python -X utf8 bot.py
echo.
echo   ------------------------------------------
echo   ربات متوقف شد. پيام بالا دليلش را مي‌گويد.
echo   ------------------------------------------
pause
