@echo off
echo ========================================
echo    Qdrant Vector Database Startup Script
echo ========================================
echo.

REM Qdrant 可执行文件路径
set QDRANT_EXE=C:\Users\Aumovio\Downloads\qdrant-x86_64-pc-windows-msvc\qdrant-x86_64-pc-windows-msvc\qdrant.exe

REM 数据目录（包含 2023, 2024, Machining collections）
set QDRANT_STORAGE=C:\Users\Aumovio\Desktop\StartServices

if not exist "%QDRANT_EXE%" (
    echo Error: qdrant.exe not found at: %QDRANT_EXE%
    pause
    exit /b 1
)

if not exist "%QDRANT_STORAGE%\storage" (
    echo Error: storage directory not found at: %QDRANT_STORAGE%\storage
    pause
    exit /b 1
)

echo Starting Qdrant from storage: %QDRANT_STORAGE%\storage
echo Ports: 6333 (REST API), 6334 (gRPC)
echo Press Ctrl+C to stop
echo.
echo ========================================
echo.

REM 从 StartServices 目录启动，确保读取正确的 storage
cd /d "%QDRANT_STORAGE%"
"%QDRANT_EXE%"

echo.
echo Qdrant service has stopped.
pause
