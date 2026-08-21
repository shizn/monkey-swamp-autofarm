@echo off
chcp 65001 >nul
rem game runs as admin; this tool must run as admin too (Windows UIPI blocks keys otherwise)
net session >nul 2>&1
if %errorlevel% equ 0 goto run
set "SELF=%~f0"
echo Requesting administrator rights - please click Yes on the UAC dialog...
powershell -NoProfile -Command "Start-Process -FilePath $env:SELF -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
start "" "C:\Users\shi_z\AppData\Local\Programs\Python\Python310\pythonw.exe" monkey_gui.py
exit /b
