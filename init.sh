#!/bin/bash

# Agentic RAG System - Environment Setup Script
# This script sets up and runs the development environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   Agentic RAG System - Setup Script   ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Add PostgreSQL@15 to PATH if it exists (Homebrew installation)
if [ -d "/opt/homebrew/opt/postgresql@15/bin" ]; then
    export PATH="/opt/homebrew/opt/postgresql@15/bin:$PATH"
    echo -e "${GREEN}[INFO]${NC} Added PostgreSQL@15 to PATH"
fi

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to check Python version
check_python() {
    if command_exists python3; then
        PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
        PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
        if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
            echo -e "${GREEN}[OK]${NC} Python $PYTHON_VERSION found"
            return 0
        else
            echo -e "${RED}[ERROR]${NC} Python 3.11+ required, found $PYTHON_VERSION"
            return 1
        fi
    else
        echo -e "${RED}[ERROR]${NC} Python 3 not found"
        return 1
    fi
}

# Function to check Node.js version
check_node() {
    if command_exists node; then
        NODE_VERSION=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
        if [ "$NODE_VERSION" -ge 18 ]; then
            echo -e "${GREEN}[OK]${NC} Node.js v$(node -v | cut -d'v' -f2) found"
            return 0
        else
            echo -e "${RED}[ERROR]${NC} Node.js 18+ required, found v$(node -v)"
            return 1
        fi
    else
        echo -e "${RED}[ERROR]${NC} Node.js not found"
        return 1
    fi
}

# Function to check PostgreSQL
check_postgres() {
    if command_exists psql; then
        PSQL_VERSION=$(psql --version | awk '{print $3}')
        echo -e "${GREEN}[OK]${NC} PostgreSQL $PSQL_VERSION found"

        # Check if PostgreSQL service is running
        if psql -U postgres -d postgres -c "SELECT 1" >/dev/null 2>&1; then
            echo -e "${GREEN}[OK]${NC} PostgreSQL service is running"

            # Check if agentic_rag database exists
            if psql -U postgres -lqt | cut -d \| -f 1 | grep -qw agentic_rag; then
                echo -e "${GREEN}[OK]${NC} Database 'agentic_rag' exists"
            else
                echo -e "${YELLOW}[INFO]${NC} Database 'agentic_rag' will be created on first backend run"
            fi
        else
            echo -e "${YELLOW}[WARN]${NC} PostgreSQL service not running - using in-memory storage fallback"
        fi

        return 0
    else
        echo -e "${YELLOW}[WARN]${NC} PostgreSQL CLI not found - using in-memory storage fallback"
        echo -e "${YELLOW}[INFO]${NC} To enable PostgreSQL persistence, ensure postgresql@15 is installed"
        return 0
    fi
}

# Check prerequisites
echo -e "${YELLOW}Checking prerequisites...${NC}"
echo ""

PREREQS_OK=true
check_python || PREREQS_OK=false
check_node || PREREQS_OK=false
check_postgres

if [ "$PREREQS_OK" = false ]; then
    echo ""
    echo -e "${RED}Prerequisites not met. Please install required software:${NC}"
    echo "  - Python 3.11 or higher"
    echo "  - Node.js 18 or higher"
    echo "  - PostgreSQL 15+ with pgvector extension"
    exit 1
fi

echo ""
echo -e "${YELLOW}Setting up backend...${NC}"

# Create and activate virtual environment
if [ ! -d "backend/venv" ]; then
    echo "Creating Python virtual environment..."
    cd backend
    python3 -m venv venv
    cd ..
fi

# Activate virtual environment and install dependencies
echo "Installing Python dependencies..."
source backend/venv/bin/activate

if [ -f "backend/requirements.txt" ]; then
    pip install --upgrade pip > /dev/null 2>&1
    pip install -r backend/requirements.txt
else
    echo -e "${YELLOW}[WARN]${NC} backend/requirements.txt not found - skipping Python dependency installation"
fi

echo ""
echo -e "${YELLOW}Setting up frontend...${NC}"

# Install Node.js dependencies
if [ -d "frontend" ]; then
    cd frontend
    if [ -f "package.json" ]; then
        echo "Installing Node.js dependencies..."
        npm install
    else
        echo -e "${YELLOW}[WARN]${NC} frontend/package.json not found - skipping Node dependency installation"
    fi
    cd ..
else
    echo -e "${YELLOW}[WARN]${NC} frontend directory not found"
fi

echo ""
echo -e "${YELLOW}Environment setup complete!${NC}"
echo ""

# Check for .env file
if [ ! -f "backend/.env" ]; then
    echo -e "${YELLOW}[INFO]${NC} No .env file found in backend directory."
    echo "  You will need to configure API keys through the UI after starting the application."
fi

echo ""
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}         Starting Development          ${NC}"
echo -e "${BLUE}========================================${NC}"
echo ""
echo "Starting services..."
echo ""

# Function to cleanup background processes on exit
cleanup() {
    echo ""
    echo -e "${YELLOW}Shutting down services...${NC}"
    kill $BACKEND_PID 2>/dev/null || true
    kill $FRONTEND_PID 2>/dev/null || true
    kill $NGROK_PID 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

# Check if ngrok is available
NGROK_AVAILABLE=false
if command_exists ngrok; then
    NGROK_AVAILABLE=true
    echo -e "${GREEN}[OK]${NC} ngrok is available"
else
    echo -e "${YELLOW}[INFO]${NC} ngrok not found - WhatsApp webhook tunneling will not be available"
    echo "  Install ngrok from: https://ngrok.com/download"
fi

# Start backend server
if [ -f "backend/main.py" ]; then
    echo -e "${GREEN}Starting backend server on http://localhost:8000${NC}"
    cd backend
    source venv/bin/activate
    uvicorn main:app --reload --host 0.0.0.0 --port 8000 &
    BACKEND_PID=$!
    cd ..
else
    echo -e "${YELLOW}[WARN]${NC} backend/main.py not found - backend will not start"
fi

# Give backend time to start
sleep 2

# Start ngrok tunnel for WhatsApp webhook (if available)
NGROK_PID=""
NGROK_URL=""
if [ "$NGROK_AVAILABLE" = true ]; then
    echo -e "${GREEN}Starting ngrok tunnel for WhatsApp webhook...${NC}"
    ngrok http 8000 --log=stdout > /tmp/ngrok.log 2>&1 &
    NGROK_PID=$!

    # Give ngrok time to start and establish tunnel
    sleep 3

    # Try to get the public URL from ngrok's local API
    NGROK_URL=$(curl -s http://127.0.0.1:4040/api/tunnels 2>/dev/null | grep -o '"public_url":"https://[^"]*"' | head -1 | cut -d'"' -f4)

    if [ -n "$NGROK_URL" ]; then
        echo -e "${GREEN}[OK]${NC} ngrok tunnel established: $NGROK_URL"
    else
        echo -e "${YELLOW}[WARN]${NC} ngrok started but could not retrieve public URL"
        echo "  Check ngrok status at: http://127.0.0.1:4040"
    fi
fi

# Start frontend dev server
if [ -f "frontend/package.json" ]; then
    echo -e "${GREEN}Starting frontend server on http://localhost:3000${NC}"
    cd frontend
    npm run dev &
    FRONTEND_PID=$!
    cd ..
else
    echo -e "${YELLOW}[WARN]${NC} frontend/package.json not found - frontend will not start"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}      Agentic RAG System Running       ${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "  ${BLUE}Frontend:${NC} http://localhost:3000"
echo -e "  ${BLUE}Backend API:${NC} http://localhost:8000"
echo -e "  ${BLUE}API Docs:${NC} http://localhost:8000/docs"
if [ -n "$NGROK_URL" ]; then
    echo ""
    echo -e "  ${BLUE}ngrok Dashboard:${NC} http://127.0.0.1:4040"
    echo -e "  ${BLUE}WhatsApp Webhook:${NC} ${NGROK_URL}/api/whatsapp/webhook"
elif [ "$NGROK_AVAILABLE" = true ]; then
    echo ""
    echo -e "  ${BLUE}ngrok Dashboard:${NC} http://127.0.0.1:4040"
    echo -e "  ${YELLOW}WhatsApp Webhook:${NC} Check Settings > WhatsApp for URL"
fi
echo ""
echo -e "  Press ${YELLOW}Ctrl+C${NC} to stop all services"
echo ""

# Wait for background processes
wait
