"""
Configuration package for A2A backend.

Provides centralized, type-safe access to all application settings
through a singleton pattern.

Usage:
    from config import settings
    
    # Access configuration
    endpoint = settings.azure_ai_foundry.project_endpoint
    port = settings.server.ui_port
"""

from config.settings import Settings, get_settings, reset_settings

# Export singleton instance for convenient access
settings = get_settings()

__all__ = ["settings", "Settings", "get_settings", "reset_settings"]
