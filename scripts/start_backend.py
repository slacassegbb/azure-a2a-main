"""
start_backend.py
----------------
Script to launch the FastAPI backend (Host Orchestrator) for local development.

Features
========
- Ensures the correct conda environment (a2a-environment) is active
- Creates conda environment from environment.yaml if needed
- Installs dependencies from requirements.txt
- Checks Azure CLI login status
- Optionally installs LibreOffice for document processing
- Starts the backend server (backend_production.py)

Usage
-----
    python start_backend.py [conda_env_name]

Default environment name: a2a-environment
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("start_backend")

DEFAULT_ENV_NAME = "a2a-environment"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def find_project_root() -> Path:
    """
    Walk upward from this file until environment.yaml is found.

    :return: Path pointing to the project root.
    :raises RuntimeError: if the file cannot be located.
    """
    here = Path(__file__).resolve()
    for candidate in [here] + list(here.parents):
        if (candidate / "environment.yaml").exists():
            return candidate
    raise RuntimeError("Could not find project root (environment.yaml not found)")


PROJECT_ROOT: Path = find_project_root()
ENV_FILE: Path = PROJECT_ROOT / "environment.yaml"
BACKEND_DIR: Path = PROJECT_ROOT / "backend"
BACKEND_SCRIPT: Path = BACKEND_DIR / "backend_production.py"
REQUIREMENTS_FILE: Path = PROJECT_ROOT / "requirements.txt"


def conda_env_exists(env_name: str) -> bool:
    """Return True if env_name exists in conda installation."""
    try:
        result = subprocess.run(
            ["conda", "env", "list"],
            check=True,
            capture_output=True,
            text=True,
        )
        return env_name in result.stdout
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to list conda environments: %s", exc.stderr.strip())
        return False


def create_conda_env(env_yaml: Path) -> None:
    """Create a conda environment from env_yaml."""
    if not env_yaml.exists():
        raise FileNotFoundError(f"{env_yaml} does not exist")

    logger.info("📦 Creating conda environment from %s", env_yaml)
    try:
        subprocess.run(
            ["conda", "env", "create", "-f", str(env_yaml)],
            check=True,
        )
        logger.info("✅ Conda environment created successfully.")
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to create conda environment: %s", exc.stderr.strip())
        raise RuntimeError("Environment creation failed") from exc


def install_dependencies() -> None:
    """Install Python dependencies using pip."""
    if not REQUIREMENTS_FILE.exists():
        raise FileNotFoundError(f"{REQUIREMENTS_FILE} does not exist")

    logger.info("📦 Installing dependencies from %s", REQUIREMENTS_FILE)
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            check=True,
        )
        logger.info("✅ Dependencies installed successfully.")
    except subprocess.CalledProcessError as exc:
        logger.error("Failed to install dependencies: %s", exc.stderr.strip())
        raise RuntimeError("Dependency installation failed") from exc


def install_libreoffice() -> bool:
    """Optionally install LibreOffice for document processing."""
    logger.info("")
    response = input("📄 Install LibreOffice for document processing? (y/n) [n]: ").strip().lower()
    
    if response != 'y':
        logger.info("Skipping LibreOffice installation.")
        return False

    logger.info("📦 Installing LibreOffice...")
    system = platform.system()
    
    try:
        if system == "Darwin":  # macOS
            subprocess.run(["brew", "install", "--cask", "LibreOffice"], check=True)
        elif system == "Windows":
            subprocess.run(["winget", "install", "TheDocumentFoundation.LibreOffice"], check=True)
        elif system == "Linux":
            subprocess.run(["sudo", "apt-get", "install", "libreoffice"], check=True)
        
        logger.info("✅ LibreOffice installed successfully.")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("⚠️  Failed to install LibreOffice: %s", exc.stderr.strip())
        return False


def check_azure_login() -> None:
    """Check if user is logged into Azure."""
    logger.info("🔐 Checking Azure login...")
    
    try:
        subprocess.run(
            ["az", "account", "show"],
            check=True,
            capture_output=True,
            text=True,
        )
        logger.info("✅ Azure login verified.")
    except FileNotFoundError:
        logger.warning("⚠️  Azure CLI not found. Install from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli")
        response = input("Continue without Azure login check? (y/n) [y]: ").strip().lower()
        if response == 'n':
            sys.exit(1)
    except subprocess.CalledProcessError:
        logger.warning("⚠️  Not logged into Azure. Run: az login")
        response = input("Continue without Azure login? (y/n) [y]: ").strip().lower()
        if response == 'n':
            sys.exit(1)


def activate_and_start_backend(env_name: str) -> None:
    """
    Activate conda environment and start the backend.
    
    If already in the correct environment, starts immediately.
    Otherwise, prints instructions.
    """
    if not BACKEND_SCRIPT.exists():
        raise FileNotFoundError(f"Backend script not found at {BACKEND_SCRIPT}")

    current_env = os.environ.get("CONDA_DEFAULT_ENV")
    
    if current_env == env_name:
        # Already in the correct environment
        logger.info("")
        logger.info("⚙️  Starting Host Orchestrator (Backend)")
        logger.info("=" * 50)
        logger.info("")
        
        # Install dependencies
        install_dependencies()
        
        # Ask about LibreOffice
        install_libreoffice()
        
        # Check Azure login
        check_azure_login()
        
        # Start backend
        logger.info("")
        logger.info("🚀 Starting backend server...")
        logger.info("   WebSocket server: http://localhost:8080")
        logger.info("   A2A Backend API: http://localhost:12000")
        logger.info("")
        
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        
        try:
            os.chdir(BACKEND_DIR)
            subprocess.run(
                [sys.executable, str(BACKEND_SCRIPT)],
                env=env,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.error("❌ Backend exited with status %s", exc.returncode)
            sys.exit(exc.returncode)
        return

    # Not in the correct environment
    if not conda_env_exists(env_name):
        logger.error("❌ Conda environment '%s' not found.", env_name)
        response = input(f"Create environment from {ENV_FILE}? (y/n) [y]: ").strip().lower()
        if response != 'n':
            create_conda_env(ENV_FILE)
        else:
            sys.exit(1)

    logger.info("")
    logger.info("📝 To launch the backend, activate the conda environment and run:")
    logger.info("")
    logger.info(f"  conda activate {env_name}")
    logger.info(f"  python {__file__}")
    logger.info("")
    logger.info("Or run this command directly:")
    logger.info(f"  conda run -n {env_name} python {__file__}")
    logger.info("")
    sys.exit(0)


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    target_env = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ENV_NAME
    try:
        activate_and_start_backend(target_env)
    except Exception as exc:  # noqa: BLE001
        logger.error("❌ Backend launch failed: %s", exc)
        sys.exit(1)

