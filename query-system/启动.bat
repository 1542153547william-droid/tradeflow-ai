@echo off
title Amazon 关键词查询分析系统
cd /d "%~dp0backend"

echo ============================================================
echo            Amazon 关键词查询分析系统 - 一键启动
echo ============================================================
echo.

where python >nul 2>nul
if errorlevel 1 goto no_python

if not exist ".venv\Scripts\python.exe" goto setup
echo [就绪] 已检测到运行环境，直接启动。
echo.
goto run

:setup
echo [首次运行] 正在初始化，请耐心等待几分钟...
echo.
echo   [1/4] 创建虚拟环境...
python -m venv .venv
if errorlevel 1 goto venv_fail
echo   [2/4] 升级 pip...
".venv\Scripts\python.exe" -m pip install --upgrade pip -q
echo   [3/4] 安装依赖库（较慢，请勿关闭窗口）...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pip_fail
echo   [4/4] 安装浏览器内核（用于爬虫，可选，失败不影响使用）...
".venv\Scripts\python.exe" -m playwright install chromium
echo.
echo [完成] 初始化结束！
echo.
goto run

:run
start "" cmd /c "timeout /t 5 >nul & start http://127.0.0.1:8000/"
echo ------------------------------------------------------------
echo   服务启动中... 浏览器将自动打开: http://127.0.0.1:8000/
echo   若未自动打开，请手动在浏览器访问上面的地址。
echo   停止服务：直接关闭本窗口，或按 Ctrl + C
echo ------------------------------------------------------------
echo.
".venv\Scripts\python.exe" -m uvicorn app.main:app --port 8000
echo.
echo 服务已停止。
pause
exit /b 0

:no_python
echo [错误] 未检测到 Python，请先安装 Python 3.9 及以上版本，
echo        安装时务必勾选 "Add Python to PATH"。
echo        下载地址: https://www.python.org/downloads/
pause
exit /b 1

:venv_fail
echo [错误] 创建虚拟环境失败。
pause
exit /b 1

:pip_fail
echo [错误] 依赖安装失败，请检查网络后重试。
pause
exit /b 1
