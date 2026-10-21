@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build-ui.ps1" %*
