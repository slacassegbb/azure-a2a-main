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

    logger.info("📦 Installing Python dependencies from requirements.txt...")
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
            check=True,
        )
        logger.info("✅ Dependencies installed successfully.")
        logger.info("")
    except subprocess.CalledProcessError as exc:
        logger.error(
            "❌ Failed to install dependencies: %s",
            exc.stderr.strip() if exc.stderr else exc,
        )
        raise RuntimeError("Dependency installation failed") from exc


def install_libreoffice() -> bool:
    """Install LibreOffice for document processing with user confirmation."""
    logger.info(
        "📄 LibreOffice is used for advanced document processing (PDF, DOCX, etc.)"
    )
    response = input("   Install LibreOffice? (y/n) [n]: ").strip().lower()

    if response != "y":
        logger.info("   ⏩ Skipping LibreOffice installation.")
        logger.info("")
        return False

    logger.info("   📦 Installing LibreOffice...")
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
            subprocess.run(["brew", "install", "--cask", "libreoffice"], check=True)
        elif system == "Windows":
            subprocess.run(
                ["winget", "install", "TheDocumentFoundation.LibreOffice"], check=True
            )
        elif system == "Linux":
            subprocess.run(["sudo", "apt-get", "install", "libreoffice"], check=True)

        logger.info("   ✅ LibreOffice installed successfully.")
        logger.info("")
        return True
    except subprocess.CalledProcessError as exc:
        logger.warning("   ⚠️  Failed to install LibreOffice: %s", exc)
        logger.info("   You can install it manually later if needed.")
        logger.info("")
        return False
    except FileNotFoundError:
        logger.warning("   ⚠️  Package manager not found.")
        logger.info(
            "   Please install LibreOffice manually if you need document processing."
        )
        logger.info("")
        return False


def check_azure_login() -> None:
    """Check if user is logged into Azure and prompt login if needed."""
    logger.info("")
    logger.info("🔐 Checking Azure login...")

    # Try to find az command (handle Windows paths)
    az_command = "az"
    if platform.system() == "Windows":
        # Try common Windows paths for Azure CLI
        possible_paths = [
            "az",
            "az.cmd",
            r"C:\Program Files (x86)\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
            r"C:\Program Files\Microsoft SDKs\Azure\CLI2\wbin\az.cmd",
        ]
        az_found = False
        for path in possible_paths:
            try:
                subprocess.run(
                    [path, "--version"],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                az_command = path
                az_found = True
                break
            except (
                FileNotFoundError,
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
            ):
                continue

        if not az_found:
            logger.warning("⚠️  Azure CLI not found in PATH.")
            logger.info("   Checking if Azure CLI is installed...")
            logger.info("")
            response = (
                input("Do you have Azure CLI installed? (y/n) [y]: ").strip().lower()
            )

            if response == "y":
                logger.info("")
                logger.info("💡 Azure CLI is installed but not in PATH.")
                logger.info("   To fix this, add Azure CLI to your PATH:")
                logger.info('   1. Search for "Environment Variables" in Windows')
                logger.info("   2. Edit System Environment Variables")
                logger.info(
                    "   3. Add to PATH: C:\\Program Files\\Microsoft SDKs\\Azure\\CLI2\\wbin"
                )
                logger.info("")
                logger.info(
                    "   OR run this script from a fresh terminal after installing Azure CLI"
                )
                logger.info("")
                response2 = (
                    input("Continue without Azure login check? (y/n) [n]: ")
                    .strip()
                    .lower()
                )
                if response2 != "y":
                    sys.exit(1)
                logger.info(
                    "⚠️  Skipping Azure login check - backend may fail if Azure credentials are missing"
                )
                logger.info("")
                return
            else:
                logger.error("❌ Azure CLI is REQUIRED to run the backend.")
                logger.info("   Install from: https://aka.ms/installazurecliwindows")
                logger.info(
                    "   After installation, restart your terminal and try again."
                )
                sys.exit(1)

    try:
        result = subprocess.run(
            [az_command, "account", "show"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        logger.info("✅ Azure login verified.")
        logger.info("")
        return
    except FileNotFoundError:
        logger.error("❌ Azure CLI not found.")
        logger.error(
            "   Install from: https://aka.ms/installazurecliwindows"
            if platform.system() == "Windows"
            else "https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        )
        logger.error("   Azure CLI is REQUIRED to run the backend.")
        sys.exit(1)
    except subprocess.TimeoutExpired:
        logger.warning("⚠️  Azure CLI check timed out.")
        response = (
            input("Continue without Azure login check? (y/n) [n]: ").strip().lower()
        )
        if response != "y":
            sys.exit(1)
        return
    except subprocess.CalledProcessError:
        # Not logged in - prompt for login
        logger.warning("⚠️  Not logged into Azure.")
        logger.info("   Azure login is REQUIRED to run the backend.")
        logger.info("")

        response = input("Run 'az login' now? (y/n) [y]: ").strip().lower()

        if response == "n":
            logger.error("❌ Cannot start backend without Azure login.")
            sys.exit(1)

        # Run az login
        logger.info("")
        logger.info("🔐 Running 'az login'...")
        logger.info("   Follow the prompts in your browser to authenticate.")
        logger.info("")

        try:
            subprocess.run([az_command, "login"], check=True)
            logger.info("")
            logger.info("✅ Azure login successful!")
            logger.info("")
        except subprocess.CalledProcessError as exc:
            logger.error("❌ Azure login failed.")
            logger.error("   Please run 'az login' manually and try again.")
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

        # Single setup prompt at the beginning
        logger.info("🔧 First time setup required:")
        logger.info("   • Install Python dependencies (pip)")
        logger.info("   • Install LibreOffice (optional document processing)")
        logger.info("")
        setup_response = input("Run first-time setup now? (y/n) [n]: ").strip().lower()
        logger.info("")

        if setup_response == "y":
            # Install dependencies
            install_dependencies()
            # Ask about LibreOffice
            install_libreoffice()
        else:
            logger.info("⏩ Skipping setup. Starting backend directly...")
            logger.info("")

        # ALWAYS check Azure login before starting backend
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
        response = (
            input(f"Create environment from {ENV_FILE}? (y/n) [y]: ").strip().lower()
        )
        if response != "n":
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
