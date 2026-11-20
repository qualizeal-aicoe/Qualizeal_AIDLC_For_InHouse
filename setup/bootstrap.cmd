@echo off
rem QualiZeal AI-DLC Studio: get this laptop ready, then check it. Safe to run again.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" %*
exit /b %errorlevel%
