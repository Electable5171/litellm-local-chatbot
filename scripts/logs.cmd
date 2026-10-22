@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0appctl.ps1" logs %*
