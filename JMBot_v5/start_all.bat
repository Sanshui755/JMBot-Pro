@echo off
chcp 65001 >nul
setlocal
title JMBot 一键启动

rem ============ 按需修改以下变量 ============
rem NapCat.Shell 目录（含 launcher-user.bat）
set "NAPCAT_DIR=C:\NapCat.Shell"
rem 本目录即 JMBot_v5（bat 放在 JMBot_v5 里则不用改）
set "BOT_DIR=%~dp0"
rem 机器人 QQ 号（NapCat 快速登录用；留空则 NapCat 弹二维码扫码）
set "BOT_QQ="
rem ncatbot 可执行文件路径（虚拟环境或全局 Python 的 Scripts 目录）
set "NCATBOT=%BOT_DIR%.venv\Scripts\ncatbot.exe"
rem =========================================

if not exist "%NCATBOT%" (
    echo [错误] 未找到 ncatbot: %NCATBOT%
    echo 请先安装 ncatbot5，或把 NCATBOT 变量改成实际路径
    pause
    exit /b 1
)
if not exist "%NAPCAT_DIR%\launcher-user.bat" (
    echo [错误] 未找到 NapCat 启动器: %NAPCAT_DIR%\launcher-user.bat
    echo 请先下载 NapCat.Shell，或把 NAPCAT_DIR 变量改成实际路径
    pause
    exit /b 1
)

echo [1/3] 启动 NapCat ...
if "%BOT_QQ%"=="" (
    start "NapCat" cmd /c "cd /d %NAPCAT_DIR% && call launcher-user.bat"
) else (
    start "NapCat-%BOT_QQ%" cmd /c "cd /d %NAPCAT_DIR% && call launcher-user.bat %BOT_QQ%"
)

echo [2/3] 等待 NapCat WebSocket 端口 3001 就绪 ...
set /a TRY=0
:wait_port
powershell -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient;$c.ConnectAsync('127.0.0.1',3001).Wait(1000)|Out-Null;exit [int](-not $c.Connected)}catch{exit 1}finally{$c.Dispose()}"
if not errorlevel 1 goto port_ok
set /a TRY+=1
if %TRY% GEQ 30 goto port_timeout
timeout /t 2 /nobreak >nul
goto wait_port
:port_timeout
echo [警告] 等待 3001 端口超时，NapCat 可能未登录成功，仍继续启动机器人...
goto start_bot
:port_ok
echo NapCat 已就绪。

:start_bot
echo [3/3] 启动 JMBot (ncatbot run) ...
cd /d "%BOT_DIR%"
"%NCATBOT%" run

echo.
echo 机器人已退出。
pause
