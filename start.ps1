# Agentic RAG System - Start Script (Windows PowerShell)
# Equivalent of start.sh for Windows environments
# Usage: .\start.ps1

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Colors
function Write-Color($Color, $Message) {
    Write-Host $Message -ForegroundColor $Color
}

# Cleanup function
$backendJob = $null
$frontendJob = $null

function Stop-AllServices {
    Write-Host ""
    Write-Color Yellow "Shutting down..."
    if ($script:backendJob) { Stop-Job $script:backendJob -ErrorAction SilentlyContinue; Remove-Job $script:backendJob -Force -ErrorAction SilentlyContinue }
    if ($script:frontendJob) { Stop-Job $script:frontendJob -ErrorAction SilentlyContinue; Remove-Job $script:frontendJob -Force -ErrorAction SilentlyContinue }

    # Also kill any uvicorn/node processes that may have been spawned
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Get-Process -Name "node" -ErrorAction SilentlyContinue | Where-Object {
        $_.MainWindowTitle -match "frontend" -or $_.CommandLine -match "vite"
    } -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

    Write-Color Green "Done."
}

# 1. Check PostgreSQL
Write-Color Yellow "Checking PostgreSQL..."
$pgReady = $false
try {
    $null = pg_isready 2>&1
    if ($LASTEXITCODE -eq 0) {
        $pgReady = $true
    }
} catch {}

if (-not $pgReady) {
    Write-Color Yellow "Starting PostgreSQL..."
    # Try common Windows PostgreSQL service names
    $pgService = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pgService) {
        Start-Service $pgService.Name -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    } else {
        Write-Color Yellow "[WARN] PostgreSQL service not found. Please start it manually."
    }
}
Write-Color Green "PostgreSQL check complete"

# 2. Start Backend
Write-Color Yellow "Starting backend on port 8000..."
$script:backendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location "$dir\backend"
    & "$dir\backend\venv\Scripts\Activate.ps1"
    uvicorn main:app --host 0.0.0.0 --port 8000
} -ArgumentList $ProjectDir

# Wait for backend to be ready
$backendReady = $false
for ($i = 1; $i -le 15; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8000/api/health" -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) {
            Write-Color Green "Backend ready"
            $backendReady = $true
            break
        }
    } catch {}
    if ($i -eq 15) {
        Write-Color Red "Backend failed to start"
        Stop-AllServices
        exit 1
    }
    Start-Sleep -Seconds 1
}

# 3. Start Frontend
Write-Color Yellow "Starting frontend on port 5173..."
$script:frontendJob = Start-Job -ScriptBlock {
    param($dir)
    Set-Location "$dir\frontend"
    npm run dev
} -ArgumentList $ProjectDir
Start-Sleep -Seconds 3

Write-Host ""
Write-Color Green "========================================"
Write-Color Green "  Agentic RAG System is running"
Write-Color Green "  Frontend: http://localhost:5173"
Write-Color Green "  Backend:  http://localhost:8000"
Write-Color Green "  API docs: http://localhost:8000/docs"
Write-Color Green "========================================"
Write-Color Yellow "Press Ctrl+C to stop"
Write-Host ""

# Wait and show output
try {
    while ($true) {
        if ($script:backendJob) { Receive-Job $script:backendJob -ErrorAction SilentlyContinue }
        if ($script:frontendJob) { Receive-Job $script:frontendJob -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
} finally {
    Stop-AllServices
}
