@echo off
REM Agentic RAG System - Setup Script (Windows)
REM This is a wrapper that launches the PowerShell setup script
REM Usage: double-click init.bat or run from Command Prompt

echo ========================================
echo    Agentic RAG System - Setup Script
echo ========================================
echo.

REM Check if PowerShell is available
where powershell >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PowerShell is required but not found.
    echo Please install PowerShell or run init.ps1 directly.
    pause
    exit /b 1
)

REM Run the PowerShell script
powershell -ExecutionPolicy Bypass -File "%~dp0init.ps1"

if %ERRORLEVEL% neq 0 (
    echo.
    echo [ERROR] Setup failed. Check the output above for details.
    pause
    exit /b %ERRORLEVEL%
)
