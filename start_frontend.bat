@echo off
echo ========================================
echo Starting React Frontend
echo ========================================
echo.

REM 获取脚本所在目录
cd /d "%~dp0"

REM 尝试添加常见的 Node.js 路径到 PATH
if exist "C:\Program Files\nodejs\" set "PATH=%PATH%;C:\Program Files\nodejs\"
if exist "C:\Program Files (x86)\nodejs\" set "PATH=%PATH%;C:\Program Files (x86)\nodejs\"
if exist "%APPDATA%\npm\" set "PATH=%PATH%;%APPDATA%\npm\"

REM 检查 npm 是否可用
where npm >nul 2>nul
if errorlevel 1 (
    echo [ERROR] npm is not installed or not in PATH!
    echo.
    echo Please install Node.js from: https://nodejs.org/
    echo Make sure to check "Add to PATH" during installation.
    echo.
    pause
    exit /b 1
)

REM 检查 frontend 目录是否存在
if not exist "frontend" (
    echo [ERROR] frontend directory not found!
    echo Current directory: %CD%
    echo.
    pause
    exit /b 1
)

echo Changing to frontend directory...
cd frontend

REM 检查 package.json 是否存在
if not exist "package.json" (
    echo [ERROR] package.json not found!
    echo Please make sure you are in the correct directory.
    echo.
    pause
    exit /b 1
)

REM 检查 node_modules 是否存在
if not exist "node_modules" (
    echo [WARNING] node_modules not found!
    echo Installing dependencies...
    echo.
    call npm install
    if errorlevel 1 (
        echo [ERROR] npm install failed!
        pause
        exit /b 1
    )
)

echo.
echo Starting Vite dev server...
echo Frontend will be available at: http://localhost:5173
echo.
echo Press Ctrl+C to stop the server
echo ========================================
echo.

npm run dev

if errorlevel 1 (
    echo.
    echo [ERROR] Failed to start frontend server!
    pause
    exit /b 1
)

pause
