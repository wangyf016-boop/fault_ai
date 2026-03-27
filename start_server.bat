@echo off
cls
echo.
echo ========================================
echo     🔧 启动 FastAPI 后端服务（UTF-8 编码）
echo     项目路径：%CD%
echo ========================================
echo.

:: 设置 UTF-8 编码
chcp 65001 >nul

:: 进入项目根目录
cd /d "%~dp0"

echo 正在激活虚拟环境...
call .venv\Scripts\activate

if errorlevel 1 (
    echo ❌ 虚拟环境激活失败！请检查 .venv 是否存在。
    pause
    exit /b 1
)

echo 正在启动 FastAPI 服务...
echo.

python -m uvicorn app.server:app ^
    --host 0.0.0.0 ^
    --port 8000 ^
    --reload

if errorlevel 1 (
    echo.
    echo ❌ 服务启动失败！请检查代码或端口是否被占用。
    pause
    exit /b 1
)

echo.
echo ✅ 服务已启动！正在打开浏览器...
start http://localhost:8000

echo.
echo 📌 服务运行中：http://localhost:8000
echo 📌 按任意键退出...
pause >nul
