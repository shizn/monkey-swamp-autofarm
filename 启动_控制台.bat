@echo off
chcp 65001 >nul
rem 带控制台的诊断启动器:能看到崩溃/报错红字。用完可回到普通"启动.bat"。
net session >nul 2>&1
if %errorlevel% equ 0 goto run
set "SELF=%~f0"
echo Requesting administrator rights - please click Yes on the UAC dialog...
powershell -NoProfile -Command "Start-Process -FilePath $env:SELF -Verb RunAs"
exit /b
:run
cd /d "%~dp0"
"C:\Users\shi_z\AppData\Local\Programs\Python\Python310\python.exe" monkey_gui.py
echo.
echo ============================================================
echo  程序已退出/崩溃。上面若有红字就是报错,请截图发我。
echo  同时 monkey_crash.log 也记录了报错。
echo ============================================================
pause >nul
exit /b
