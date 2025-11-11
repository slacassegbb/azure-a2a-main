# Startup Scripts

This directory contains scripts to easily start the backend and frontend services.

## 🚀 Quick Start

### On Windows (PowerShell)

```powershell
# Terminal 1: Start Backend
.\scripts\start_backend.ps1

# Terminal 2: Start Frontend
.\scripts\start_frontend.ps1
```

### On macOS/Linux (Bash)

```bash
# Terminal 1: Start Backend
./scripts/start_backend.sh

# Terminal 2: Start Frontend
./scripts/start_frontend.sh
```

## ⚙️ Backend (Host Orchestrator)

**What it does:**
- Creates and activates a Python virtual environment (`.venv`)
- Installs all required dependencies from `requirements.txt`
- Checks Azure CLI login status
- Starts the backend server

**Endpoints:**
- WebSocket server: `http://localhost:8080`
- A2A Backend API: `http://localhost:12000`

**Scripts:**
- `start_backend.ps1` - PowerShell version (Windows)
- `start_backend.sh` - Bash version (macOS/Linux)

## 🖥️ Frontend (Multi-Agent UI)

**What it does:**
- Installs Node.js dependencies
- Starts the Next.js development server

**Endpoints:**
- Frontend UI: `http://localhost:3000`
- Connects to WebSocket backend at `http://localhost:8080`

**Scripts:**
- `start_frontend.ps1` - PowerShell version (Windows)
- `start_frontend.sh` - Bash version (macOS/Linux)

## 📋 Prerequisites

### Backend Requirements
- Python 3.8 or higher
- Azure CLI (optional, but recommended)
  - Install: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli
  - Login: `az login`

### Frontend Requirements
- Node.js (LTS version recommended)
  - Download: https://nodejs.org/en/download/

## 🔧 Troubleshooting

### Backend Issues

**Virtual environment activation fails:**
- Windows: Run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Linux/Mac: Ensure script is executable with `chmod +x scripts/start_backend.sh`

**Azure login errors:**
- Run `az login` in your terminal
- Or choose to continue without Azure login when prompted

**Module import errors:**
- The script reinstalls dependencies automatically
- If issues persist, delete `.venv` folder and run script again

### Frontend Issues

**Port 3000 already in use:**
- Stop any other process using port 3000
- Or modify `next.config.mjs` to use a different port

**Node modules issues:**
- Delete `node_modules` and `package-lock.json`
- Run the script again to reinstall

## 📝 Notes

- Both services should be running simultaneously for full functionality
- Backend must be started before frontend for WebSocket connection
- Keep both terminal windows open while using the application
