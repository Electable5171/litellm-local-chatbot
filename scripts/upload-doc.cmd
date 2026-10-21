@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0upload-doc.ps1" %*
