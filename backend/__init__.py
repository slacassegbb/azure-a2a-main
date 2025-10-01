"""Backend package for A2A backend services."""

from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent
DATA_DIR = BACKEND_ROOT / "data"
HOSTS_DIR = BACKEND_ROOT / "hosts"

__all__ = ["BACKEND_ROOT", "DATA_DIR", "HOSTS_DIR"]
