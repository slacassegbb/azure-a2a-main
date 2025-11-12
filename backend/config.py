"""
Centralized configuration management for A2A Backend.

All environment variables and defaults are defined here for easy maintenance.
This module provides type-safe access to configuration with validation.
"""
import os
from pathlib import Path
from typing import Optional
from dataclasses import dataclass


# ============================================================================
# Directory Configuration
# ============================================================================
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOADS_DIR = BASE_DIR / "uploads"
HOSTS_DIR = BASE_DIR / "hosts"
VOICE_RECORDINGS_DIR = BASE_DIR / "voice_recordings"
HOST_AGENT_FILES_DIR = BASE_DIR / "host_agent_files"


def ensure_directories() -> None:
    """Create all required directories if they don't exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    VOICE_RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    HOST_AGENT_FILES_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Configuration Class
# ============================================================================
@dataclass
class Config:
    """Type-safe configuration for A2A backend."""

    # ========================================================================
    # Server Configuration
    # ========================================================================
    host: str
    port: int
    debug_mode: bool
    verbose_logging: bool

    # ========================================================================
    # A2A System Configuration
    # ========================================================================
    a2a_host: str  # "FOUNDRY" or "AZURE_SDK"
    websocket_server_url: str
    websocket_port: int

    # ========================================================================
    # Security Configuration
    # ========================================================================
    secret_key: str
    jwt_algorithm: str

    # ========================================================================
    # Azure Configuration
    # ========================================================================
    azure_tenant_id: Optional[str]
    azure_client_id: Optional[str]
    azure_client_secret: Optional[str]

    # Azure AI Services
    azure_ai_service_endpoint: Optional[str]
    azure_ai_service_api_version: str

    # Azure Content Understanding (legacy)
    azure_content_understanding_endpoint: Optional[str]
    azure_content_understanding_api_version: str

    # Azure Storage
    azure_storage_account_name: Optional[str]
    azure_blob_container: str

    # ========================================================================
    # Voice Live API Configuration
    # ========================================================================
    voice_live_api_key: Optional[str]

    # ========================================================================
    # File Paths
    # ========================================================================
    users_file: Path
    sessions_file: Path
    agent_registry_file: Path

    def validate(self) -> list[str]:
        """
        Validate configuration and return list of warnings.

        Returns:
            List of warning messages for missing optional config.
        """
        warnings = []

        if self.secret_key == "change-me":
            warnings.append(
                "⚠️  SECRET_KEY is using default value - set in production!"
            )

        if not self.azure_tenant_id:
            warnings.append("⚠️  AZURE_TENANT_ID not set - Azure auth may not work")

        if not self.azure_client_id:
            warnings.append("⚠️  AZURE_CLIENT_ID not set - Azure auth may not work")

        if not self.voice_live_api_key:
            warnings.append("⚠️  VOICE_LIVE_API_KEY not set - voice features disabled")

        if not self.azure_storage_account_name:
            warnings.append(
                "⚠️  AZURE_STORAGE_ACCOUNT_NAME not set - blob storage disabled"
            )

        return warnings


# ============================================================================
# Configuration Loading
# ============================================================================
def _get_bool(key: str, default: bool = False) -> bool:
    """Get boolean value from environment variable."""
    value = os.environ.get(key, str(default)).lower()
    return value in ("true", "1", "yes", "on")


def _get_int(key: str, default: int) -> int:
    """Get integer value from environment variable."""
    value = os.environ.get(key, str(default))
    try:
        return int(value)
    except ValueError:
        return default


def load_config() -> Config:
    """
    Load configuration from environment variables with defaults.

    Returns:
        Validated Config instance.
    """
    config = Config(
        # Server
        host=os.environ.get("A2A_UI_HOST", "0.0.0.0"),
        port=_get_int("A2A_UI_PORT", 12000),
        debug_mode=_get_bool("DEBUG_MODE", False),
        verbose_logging=_get_bool("VERBOSE_LOGGING", False),
        # A2A System
        a2a_host=os.environ.get("A2A_HOST", "FOUNDRY"),
        websocket_server_url=os.environ.get(
            "WEBSOCKET_SERVER_URL", "http://localhost:8080"
        ),
        websocket_port=_get_int("WEBSOCKET_PORT", 8080),
        # Security
        secret_key=os.environ.get("SECRET_KEY", "change-me"),
        jwt_algorithm=os.environ.get("JWT_ALGORITHM", "HS256"),
        # Azure
        azure_tenant_id=os.environ.get("AZURE_TENANT_ID"),
        azure_client_id=os.environ.get("AZURE_CLIENT_ID"),
        azure_client_secret=os.environ.get("AZURE_CLIENT_SECRET"),
        # Azure AI Services
        azure_ai_service_endpoint=os.environ.get(
            "AZURE_AI_SERVICE_ENDPOINT",
            os.environ.get("AZURE_CONTENT_UNDERSTANDING_ENDPOINT"),
        ),
        azure_ai_service_api_version=os.environ.get(
            "AZURE_AI_SERVICE_API_VERSION", "2024-12-01-preview"
        ),
        # Azure Content Understanding (legacy)
        azure_content_understanding_endpoint=os.environ.get(
            "AZURE_CONTENT_UNDERSTANDING_ENDPOINT"
        ),
        azure_content_understanding_api_version=os.environ.get(
            "AZURE_CONTENT_UNDERSTANDING_API_VERSION", "2024-12-01-preview"
        ),
        # Azure Storage
        azure_storage_account_name=os.environ.get("AZURE_STORAGE_ACCOUNT_NAME"),
        azure_blob_container=os.environ.get("AZURE_BLOB_CONTAINER", "a2a-files"),
        # Voice
        voice_live_api_key=os.environ.get("VOICE_LIVE_API_KEY"),
        # File paths
        users_file=DATA_DIR / "users.json",
        sessions_file=DATA_DIR / "sessions.json",
        agent_registry_file=DATA_DIR / "agent_registry.json",
    )

    return config


# ============================================================================
# Global Configuration Instance
# ============================================================================
# This is loaded once at module import time
config = load_config()

# Ensure directories exist
ensure_directories()


# ============================================================================
# Configuration Display
# ============================================================================
def display_config_summary() -> None:
    """Print configuration summary for debugging."""
    print("\n" + "=" * 60)
    print("🔧 A2A Backend Configuration")
    print("=" * 60)
    print(f"Server:              {config.host}:{config.port}")
    print(f"A2A Host:            {config.a2a_host}")
    print(f"WebSocket URL:       {config.websocket_server_url}")
    print(f"Debug Mode:          {config.debug_mode}")
    print(f"Verbose Logging:     {config.verbose_logging}")
    print(f"Azure Tenant:        {config.azure_tenant_id or 'Not set'}")
    print(
        f"Voice API Key:       {'✓ Set' if config.voice_live_api_key else '✗ Not set'}"
    )
    print(f"Storage Account:     {config.azure_storage_account_name or 'Not set'}")
    print("=" * 60)

    # Display warnings
    warnings = config.validate()
    if warnings:
        print("\n⚠️  Configuration Warnings:")
        for warning in warnings:
            print(f"   {warning}")
        print()


if __name__ == "__main__":
    # Test configuration loading
    display_config_summary()
