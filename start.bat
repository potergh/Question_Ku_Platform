@echo off
chcp 65001 >nul
echo ============================================
echo   智能题库讲义制作平台 - 启动
echo ============================================
echo.

REM Check venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] 虚拟环境不存在，请先运行 setup.bat 安装
    pause
    exit /b 1
)

echo 正在启动服务...
echo.

REM Activate venv and start server
call venv\Scripts\activate.bat
cd backend

REM Start uvicorn
echo 平台地址: http://localhost:8000
echo 按 Ctrl+C 停止服务
echo.

REM Open browser after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

REM Start server (blocking)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
