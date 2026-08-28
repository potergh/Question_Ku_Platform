@echo off
chcp 65001 >nul
echo ============================================
echo   智能题库讲义制作平台 - 安装脚本
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.11+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/5] 创建 Python 虚拟环境...
if not exist "venv" (
    python -m venv venv
    echo   虚拟环境已创建
) else (
    echo   虚拟环境已存在，跳过
)

echo.
echo [2/5] 安装后端依赖...
call venv\Scripts\activate.bat
pip install -r backend\requirements.txt -q
echo   后端依赖安装完成

echo.
echo [3/5] 安装 Playwright 浏览器...
python -m playwright install chromium
echo   Playwright 安装完成

echo.
echo [4/5] 检查 Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo   [SKIP] 未找到 Node.js，跳过前端构建
    echo   如需开发前端，请安装 Node.js 18+
) else (
    echo   Node.js 已安装，构建前端...
    cd frontend
    call npm install -q
    call npm run build
    cd ..
    echo   前端构建完成
)

echo.
echo [5/5] 初始化数据库...
cd backend
call ..\venv\Scripts\activate.bat
python -m alembic upgrade head
python -m app.init_tags 2>nul
cd ..
echo   数据库初始化完成

echo.
echo ============================================
echo   安装完成！运行 start.bat 启动平台
echo ============================================
pause
