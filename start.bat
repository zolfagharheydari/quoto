@echo off
chcp 65001 >nul
title Quote Bot
cd /d "%~dp0"
echo.
echo   ربات در حال روشن شدن...
echo   براي خاموش کردن، همين پنجره را ببنديد يا Ctrl+C بزنيد.
echo.
python bot.py
echo.
echo   ------------------------------------------
echo   ربات متوقف شد. پيام بالا دليلش را مي‌گويد.
echo   ------------------------------------------
pause
