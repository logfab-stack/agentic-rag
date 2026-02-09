# Agentic RAG System - Environment Setup Script (Windows PowerShell)
# Equivalent of init.sh for Windows environments
# Usage: .\init.ps1

$ErrorActionPreference = "Stop"

# Colors for output
function Write-Color($Color, $Message) {
    Write-Host $Message -ForegroundColor $Color
}

Write-Color Cyan "========================================"
Write-Color Cyan "   Agentic RAG System - Setup Script   "
Write-Color Cyan "========================================"
Write-Host ""

# Get the directory where the script is located
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# Function to check if a command exists
function Test-CommandExists($Command) {
    $null -ne (Get-Command $Command -ErrorAction SilentlyContinue)
}

# Function to check Python version
function Test-Python {
    $pythonCmd = if (Test-CommandExists "python") { "python" }
                 elseif (Test-CommandExists "python3") { "python3" }
                 else { $null }

    if ($null -eq $pythonCmd) {
        Write-Color Red "[ERROR] Python not found"
        return $false
    }

    $version = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    $major, $minor = $version -split '\.'
    if ([int]$major -ge 3 -and [int]$minor -ge 11) {
        Write-Color Green "[OK] Python $version found"
        return $true
    } else {
        Write-Color Red "[ERROR] Python 3.11+ required, found $version"
        return $false
    }
}

# Function to check Node.js version
function Test-Node {
    if (-not (Test-CommandExists "node")) {
        Write-Color Red "[ERROR] Node.js not found"
        return $false
    }

    $version = (node -v) -replace 'v', ''
    $major = ($version -split '\.')[0]
    if ([int]$major -ge 18) {
        Write-Color Green "[OK] Node.js v$version found"
        return $true
    } else {
        Write-Color Red "[ERROR] Node.js 18+ required, found v$version"
        return $false
    }
}

# Function to check PostgreSQL
function Test-Postgres {
    if (Test-CommandExists "psql") {
        $version = (psql --version) -replace '.*\s(\d+\.\d+).*', '$1'
        Write-Color Green "[OK] PostgreSQL $version found"

        # Check if PostgreSQL service is running
        try {
            $null = psql -U postgres -d postgres -c "SELECT 1" 2>&1
            Write-Color Green "[OK] PostgreSQL service is running"

            # Check if agentic_rag database exists
            $databases = psql -U postgres -lqt 2>&1
            if ($databases -match "agentic_rag") {
                Write-Color Green "[OK] Database 'agentic_rag' exists"
            } else {
                Write-Color Yellow "[INFO] Database 'agentic_rag' will be created on first backend run"
            }
        } catch {
            Write-Color Yellow "[WARN] PostgreSQL service not running - using in-memory storage fallback"
        }
        return $true
    } else {
        Write-Color Yellow "[WARN] PostgreSQL CLI not found - using in-memory storage fallback"
        Write-Color Yellow "[INFO] To enable PostgreSQL persistence, ensure PostgreSQL is installed"
        return $true
    }
}

# Check prerequisites
Write-Color Yellow "Checking prerequisites..."
Write-Host ""

$prereqsOk = $true
if (-not (Test-Python)) { $prereqsOk = $false }
if (-not (Test-Node)) { $prereqsOk = $false }
Test-Postgres | Out-Null

if (-not $prereqsOk) {
    Write-Host ""
    Write-Color Red "Prerequisites not met. Please install required software:"
    Write-Host "  - Python 3.11 or higher"
    Write-Host "  - Node.js 18 or higher"
    Write-Host "  - PostgreSQL 15+ with pgvector extension"
    exit 1
}

Write-Host ""
Write-Color Yellow "Setting up backend..."

# Determine python command
$pythonCmd = if (Test-CommandExists "python") { "python" } else { "python3" }

# Create and activate virtual environment
if (-not (Test-Path "backend\venv")) {
    Write-Host "Creating Python virtual environment..."
    Push-Location backend
    & $pythonCmd -m venv venv
    Pop-Location
}

# Activate virtual environment and install dependencies
Write-Host "Installing Python dependencies..."
& "backend\venv\Scripts\Activate.ps1"

if (Test-Path "backend\requirements.txt") {
    pip install --upgrade pip 2>&1 | Out-Null
    pip install -r backend\requirements.txt
} else {
    Write-Color Yellow "[WARN] backend\requirements.txt not found - skipping Python dependency installation"
}

Write-Host ""
Write-Color Yellow "Setting up frontend..."

# Install Node.js dependencies
if (Test-Path "frontend") {
    Push-Location frontend
    if (Test-Path "package.json") {
        Write-Host "Installing Node.js dependencies..."
        npm install
    } else {
        Write-Color Yellow "[WARN] frontend\package.json not found - skipping Node dependency installation"
    }
    Pop-Location
} else {
    Write-Color Yellow "[WARN] frontend directory not found"
}

Write-Host ""
Write-Color Yellow "Environment setup complete!"
Write-Host ""

# Check for .env file
if (-not (Test-Path "backend\.env")) {
    Write-Color Yellow "[INFO] No .env file found in backend directory."
    Write-Host "  You will need to configure API keys through the UI after starting the application."
}

Write-Host ""
Write-Color Cyan "========================================"
Write-Color Cyan "         Starting Development          "
Write-Color Cyan "========================================"
Write-Host ""
Write-Host "Starting services..."
Write-Host ""

# Start backend server
$backendJob = $null
$frontendJob = $null

if (Test-Path "backend\main.py") {
    Write-Color Green "Starting backend server on http://localhost:8000"
    $backendJob = Start-Job -ScriptBlock {
        param($dir, $pythonCmd)
        Set-Location "$dir\backend"
        & "$dir\backend\venv\Scripts\Activate.ps1"
        uvicorn main:app --reload --host 0.0.0.0 --port 8000
    } -ArgumentList $ScriptDir, $pythonCmd
} else {
    Write-Color Yellow "[WARN] backend\main.py not found - backend will not start"
}

# Give backend time to start
Start-Sleep -Seconds 2

# Start frontend dev server
if (Test-Path "frontend\package.json") {
    Write-Color Green "Starting frontend server on http://localhost:3000"
    $frontendJob = Start-Job -ScriptBlock {
        param($dir)
        Set-Location "$dir\frontend"
        npm run dev
    } -ArgumentList $ScriptDir
} else {
    Write-Color Yellow "[WARN] frontend\package.json not found - frontend will not start"
}

Write-Host ""
Write-Color Green "========================================"
Write-Color Green "      Agentic RAG System Running       "
Write-Color Green "========================================"
Write-Host ""
Write-Color Cyan "  Frontend: http://localhost:3000"
Write-Color Cyan "  Backend API: http://localhost:8000"
Write-Color Cyan "  API Docs: http://localhost:8000/docs"
Write-Host ""
Write-Color Yellow "  Press Ctrl+C to stop all services"
Write-Host ""

# Handle cleanup on Ctrl+C
try {
    while ($true) {
        # Show output from jobs
        if ($backendJob) { Receive-Job $backendJob -ErrorAction SilentlyContinue }
        if ($frontendJob) { Receive-Job $frontendJob -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 1
    }
} finally {
    Write-Host ""
    Write-Color Yellow "Shutting down services..."
    if ($backendJob) { Stop-Job $backendJob -ErrorAction SilentlyContinue; Remove-Job $backendJob -Force -ErrorAction SilentlyContinue }
    if ($frontendJob) { Stop-Job $frontendJob -ErrorAction SilentlyContinue; Remove-Job $frontendJob -Force -ErrorAction SilentlyContinue }
    Write-Color Green "Done."
}
