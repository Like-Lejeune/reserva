@echo off
rem Double-cliquez pour lancer Reserva sur ce poste. Options : voir lancer-local.ps1
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0lancer-local.ps1" %*
pause
