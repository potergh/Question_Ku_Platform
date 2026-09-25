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
echo [热重载已开启] 改动 backend\ 或 packages\ 下的 .py 会自动重启服务。
echo   注意：重启会把**正在跑的识别**标记成「服务器重启，任务中断」，
echo         （run 一次 4-5 分钟还花额度），所以跑批期间别改 .py。
echo         backend\scripts\_tmp*.py 已排除，不触发重启。
echo.

REM Open browser after 2 seconds
start /b cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:8000"

REM Start server (blocking)
rem  --reload
rem      改 .py 自动重启。代价见上面那行提示：重启会中断正在跑的识别。
rem  --reload-dir .
rem      热重载默认只盯**启动目录**（这里是 backend），显式写出更好读。
rem  --reload-dir ..\packages
rem      这一项不能漏：切题算法在 packages\physics_paper_splitter\，在 backend 外面。
rem      不指过去的话，改了切题算法不会触发重载，表现为"改了没反应"。
rem  --reload-exclude "*_tmp*"
rem      调试用的临时探针脚本不触发重启，免得随手放个 _tmp_*.py 就把正在跑的批打断。
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir . --reload-dir ..\packages --reload-exclude "*_tmp*"
