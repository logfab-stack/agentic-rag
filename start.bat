@echo off
REM Agentic RAG System - Start Script (Windows)
REM This is a wrapper that launches the PowerShell start script
REM Usage: double-click start.bat or run from Command Prompt

echo ========================================
echo    Agentic RAG System - Start
echo ========================================
echo.

REM Check if PowerShell is available
where powershell >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PowerShell is required but not found.
    echo Please install PowerShell or run start.ps1 directly.
    pause
    exit /b 1
)

REM Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Start failed. Check the output above for details.
    pause
    exit /b %ERRORLEVEL%
)
