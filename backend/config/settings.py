"""
Centralized configuration management for A2A backend.

This module provides type-safe access to all environment variables with validation,
defaults, and comprehensive documentation. Configuration is loaded once at startup
and exposed via a singleton pattern.

Usage:
    from config.settings import get_settings
    
    settings = get_settings()
    endpoint = settings.azure_ai_foundry.project_endpoint
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

from utils.ml_logging import get_logger


# Initialize module-level logger
_logger = get_logger("backend.config.settings")


class AzureAIFoundrySettings(BaseModel):
    """
    Azure AI Foundry and OpenAI configuration.
    
    Required for AI Foundry-hosted agents including model endpoints,
    API keys, and deployment configurations.
    """
    
    project_endpoint: str = Field(
        default="",
        description="Azure AI Foundry project endpoint URL"
    )
    agent_model_deployment_name: str = Field(
        default="gpt-4o",
        description="Model deployment name for agent operations"
    )
    openai_gpt_api_base: str = Field(
        default="",
        description="Azure OpenAI API base endpoint"
    )
    openai_gpt_api_key: str = Field(
        default="",
        description="Azure OpenAI API key"
    )
    openai_gpt_api_version: str = Field(
        default="",
        description="Azure OpenAI API version"
    )
    openai_gpt_deployment: str = Field(
        default="gpt-4o",
        description="GPT model deployment name"
    )
    
    @field_validator("project_endpoint", "openai_gpt_api_base")
    @classmethod
    def validate_endpoints(cls, v: str) -> str:
        """
        Validate endpoint URLs are properly formatted.
        
        :param v: The endpoint URL to validate
        :return: The validated endpoint URL
        :raises ValueError: If endpoint format is invalid
        """
        if v and not (v.startswith("http://") or v.startswith("https://")):
            _logger.warning(f"Endpoint does not start with http:// or https://: {v}")
        return v


class AzureOpenAIEmbeddingsSettings(BaseModel):
    """
    Azure OpenAI Embeddings configuration.
    
    Used for memory/search operations requiring vector embeddings.
    """
    
    endpoint: str = Field(
        default="",
        description="Azure OpenAI embeddings endpoint"
    )
    deployment: str = Field(
        default="text-embedding-3-large",
        description="Embeddings model deployment name"
    )
    key: str = Field(
        default="",
        description="Azure OpenAI embeddings API key"
    )


class AzureSearchSettings(BaseModel):
    """
    Azure Cognitive Search configuration.
    
    Used for memory operations, vector search, and semantic retrieval.
    """
    
    service_endpoint: str = Field(
        default="",
        description="Azure Search service endpoint URL"
    )
    admin_key: str = Field(
        default="",
        description="Azure Search admin API key"
    )
    index_name: str = Field(
        default="a2a-agent-interactions",
        description="Search index name for agent interactions"
    )
    vector_dimension: int = Field(
        default=1536,
        description="Vector dimension for embeddings"
    )
    vector_profile_name: str = Field(
        default="a2a-vector-profile",
        description="Vector search profile name"
    )
    vector_algorithm_name: str = Field(
        default="a2a-hnsw-config",
        description="Vector algorithm configuration name"
    )
    
    @field_validator("vector_dimension")
    @classmethod
    def validate_vector_dimension(cls, v: int) -> int:
        """
        Validate vector dimension is positive.
        
        :param v: Vector dimension value
        :return: Validated vector dimension
        :raises ValueError: If dimension is not positive
        """
        if v <= 0:
            raise ValueError(f"Vector dimension must be positive, got {v}")
        return v


class AzureStorageSettings(BaseModel):
    """
    Azure Blob Storage configuration.
    
    Used for cloud file storage with support for both managed identity
    and connection string authentication.
    """
    
    connection_string: Optional[str] = Field(
        default=None,
        description="Storage connection string (legacy auth method)"
    )
    account_name: str = Field(
        default="",
        description="Storage account name"
    )
    blob_container: str = Field(
        default="a2a-files",
        description="Blob container name for file storage"
    )
    blob_size_threshold: int = Field(
        default=1048576,
        description="File size threshold for blob storage in bytes (1MB default)"
    )
    force_azure_blob: bool = Field(
        default=True,
        description="Force use of Azure Blob storage for all files"
    )
    
    @field_validator("blob_size_threshold")
    @classmethod
    def validate_threshold(cls, v: int) -> int:
        """
        Validate blob size threshold is reasonable.
        
        :param v: Threshold value in bytes
        :return: Validated threshold
        :raises ValueError: If threshold is negative
        """
        if v < 0:
            raise ValueError(f"Blob size threshold must be non-negative, got {v}")
        return v


class AzureContentUnderstandingSettings(BaseModel):
    """
    Azure Content Understanding configuration.
    
    Used for document processing and multimodal content analysis.
    """
    
    endpoint: str = Field(
        default="",
        description="Content Understanding service endpoint"
    )
    api_version: str = Field(
        default="2024-12-01-preview",
        description="Content Understanding API version"
    )
    ai_service_endpoint: str = Field(
        default="",
        description="Azure AI Service endpoint (fallback)"
    )
    ai_service_api_version: str = Field(
        default="2024-12-01-preview",
        description="Azure AI Service API version"
    )


class ServerSettings(BaseModel):
    """
    Backend server and WebSocket configuration.
    
    Controls server binding, ports, and internal service URLs.
    """
    
    a2a_host: str = Field(
        default="FOUNDRY",
        description="A2A host type (FOUNDRY or ADK)"
    )
    ui_host: str = Field(
        default="0.0.0.0",
        description="Server bind address"
    )
    ui_port: int = Field(
        default=12000,
        description="Server port number"
    )
    backend_server_url: str = Field(
        default="http://localhost:12000",
        description="Backend server URL for internal references"
    )
    websocket_server_url: str = Field(
        default="http://localhost:8080",
        description="WebSocket server URL for event streaming"
    )
    debug_mode: bool = Field(
        default=False,
        description="Enable debug mode"
    )
    verbose_logging: bool = Field(
        default=False,
        description="Enable verbose logging output"
    )
    
    @field_validator("ui_port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """
        Validate port number is in valid range.
        
        :param v: Port number
        :return: Validated port number
        :raises ValueError: If port is out of range
        """
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v


class AuthenticationSettings(BaseModel):
    """
    Authentication and security configuration.
    
    Manages JWT tokens, secrets, and Azure AD integration.
    """
    
    secret_key: str = Field(
        default="change-me",
        description="Secret key for JWT token signing"
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="JWT signing algorithm"
    )
    azure_tenant_id: Optional[str] = Field(
        default=None,
        description="Azure AD tenant ID"
    )
    azure_client_id: Optional[str] = Field(
        default=None,
        description="Azure AD client ID"
    )
    
    @field_validator("secret_key")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """
        Validate secret key is not using default insecure value.
        
        :param v: Secret key value
        :return: Secret key value
        """
        if v == "change-me":
            _logger.warning(
                "SECRET_KEY is using default value 'change-me'. "
                "This is insecure for production!"
            )
        return v


class TelemetrySettings(BaseModel):
    """
    Application Insights and telemetry configuration.
    
    Optional monitoring and tracing for Azure AI Foundry agent operations.
    """
    
    application_insights_connection_string: Optional[str] = Field(
        default=None,
        description="Application Insights connection string"
    )


class GoogleADKSettings(BaseModel):
    """
    Google ADK configuration.
    
    Used for Google-based remote agents integration.
    """
    
    api_key: str = Field(
        default="",
        description="Google API key"
    )
    use_vertexai: bool = Field(
        default=False,
        description="Use Vertex AI instead of standard Google AI"
    )


class A2ABehaviorSettings(BaseModel):
    """
    A2A protocol behavior and tuning parameters.
    
    Controls agent-to-agent communication behavior and context handling.
    """
    
    include_last_host_turn: bool = Field(
        default=True,
        description="Include last host turn in agent context"
    )
    last_host_turn_max_chars: Optional[int] = Field(
        default=None,
        description="Maximum characters for last host turn context"
    )
    last_host_turns: int = Field(
        default=1,
        description="Number of last host turns to include"
    )
    memory_summary_max_chars: int = Field(
        default=2000,
        description="Maximum characters for memory summary"
    )
    
    @field_validator("last_host_turns", "memory_summary_max_chars")
    @classmethod
    def validate_positive(cls, v: int) -> int:
        """
        Validate numeric parameters are positive.
        
        :param v: Value to validate
        :return: Validated value
        :raises ValueError: If value is not positive
        """
        if v <= 0:
            raise ValueError(f"Value must be positive, got {v}")
        return v


class Settings(BaseModel):
    """
    Main application settings combining all configuration domains.
    
    This is the primary configuration class that aggregates all subsystem
    settings into a single cohesive configuration object. It loads environment
    variables from the .env file and provides type-safe access to all settings.
    
    :ivar azure_ai_foundry: Azure AI Foundry configuration
    :ivar azure_openai_embeddings: Azure OpenAI Embeddings configuration
    :ivar azure_search: Azure Cognitive Search configuration
    :ivar azure_storage: Azure Blob Storage configuration
    :ivar azure_content_understanding: Azure Content Understanding configuration
    :ivar server: Backend server configuration
    :ivar auth: Authentication and security configuration
    :ivar telemetry: Telemetry and monitoring configuration
    :ivar google_adk: Google ADK configuration
    :ivar a2a_behavior: A2A protocol behavior configuration
    """
    
    azure_ai_foundry: AzureAIFoundrySettings
    azure_openai_embeddings: AzureOpenAIEmbeddingsSettings
    azure_search: AzureSearchSettings
    azure_storage: AzureStorageSettings
    azure_content_understanding: AzureContentUnderstandingSettings
    server: ServerSettings
    auth: AuthenticationSettings
    telemetry: TelemetrySettings
    google_adk: GoogleADKSettings
    a2a_behavior: A2ABehaviorSettings


# Global singleton instance
_settings_instance: Optional[Settings] = None


def _load_env_bool(key: str, default: bool = False) -> bool:
    """
    Load boolean value from environment variable.
    
    :param key: Environment variable key
    :param default: Default value if not set
    :return: Boolean value
    """
    value = os.getenv(key, str(default)).lower()
    return value in ("true", "1", "yes")


def _load_env_int(key: str, default: int) -> int:
    """
    Load integer value from environment variable.
    
    :param key: Environment variable key
    :param default: Default value if not set or invalid
    :return: Integer value
    """
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError) as e:
        _logger.warning(f"Invalid integer for {key}, using default {default}: {e}")
        return default


def _create_settings() -> Settings:
    """
    Create and initialize Settings instance from environment.
    
    Loads environment variables from .env file and constructs the complete
    settings hierarchy with validation and defaults.
    
    :return: Initialized Settings instance
    :raises ValueError: If required settings are missing or invalid
    """
    try:
        # Load .env file from repository root
        backend_dir = Path(__file__).resolve().parent.parent
        root_dir = backend_dir.parent
        env_path = root_dir / ".env"
        
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            _logger.debug(f"Loaded environment from {env_path}")
        else:
            _logger.warning(f"No .env file found at {env_path}")
        
        # Build settings hierarchy
        settings = Settings(
            azure_ai_foundry=AzureAIFoundrySettings(
                project_endpoint=os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT", ""),
                agent_model_deployment_name=os.getenv(
                    "AZURE_AI_AGENT_MODEL_DEPLOYMENT_NAME", "gpt-4o"
                ),
                openai_gpt_api_base=os.getenv("AZURE_OPENAI_GPT_API_BASE", ""),
                openai_gpt_api_key=os.getenv("AZURE_OPENAI_GPT_API_KEY", ""),
                openai_gpt_api_version=os.getenv("AZURE_OPENAI_GPT_API_VERSION", ""),
                openai_gpt_deployment=os.getenv("AZURE_OPENAI_GPT_DEPLOYMENT", "gpt-4o"),
            ),
            azure_openai_embeddings=AzureOpenAIEmbeddingsSettings(
                endpoint=os.getenv("AZURE_OPENAI_EMBEDDINGS_ENDPOINT", ""),
                deployment=os.getenv(
                    "AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT", "text-embedding-3-large"
                ),
                key=os.getenv("AZURE_OPENAI_EMBEDDINGS_KEY", ""),
            ),
            azure_search=AzureSearchSettings(
                service_endpoint=os.getenv("AZURE_SEARCH_SERVICE_ENDPOINT", ""),
                admin_key=os.getenv("AZURE_SEARCH_ADMIN_KEY", ""),
                index_name=os.getenv(
                    "AZURE_SEARCH_INDEX_NAME", "a2a-agent-interactions"
                ),
                vector_dimension=_load_env_int("AZURE_SEARCH_VECTOR_DIMENSION", 1536),
                vector_profile_name=os.getenv(
                    "AZURE_SEARCH_VECTOR_PROFILE", "a2a-vector-profile"
                ),
                vector_algorithm_name=os.getenv(
                    "AZURE_SEARCH_VECTOR_ALGORITHM", "a2a-hnsw-config"
                ),
            ),
            azure_storage=AzureStorageSettings(
                connection_string=os.getenv("AZURE_STORAGE_CONNECTION_STRING"),
                account_name=os.getenv("AZURE_STORAGE_ACCOUNT_NAME", ""),
                blob_container=os.getenv("AZURE_BLOB_CONTAINER", "a2a-files"),
                blob_size_threshold=_load_env_int("AZURE_BLOB_SIZE_THRESHOLD", 1048576),
                force_azure_blob=_load_env_bool("FORCE_AZURE_BLOB", True),
            ),
            azure_content_understanding=AzureContentUnderstandingSettings(
                endpoint=os.getenv("AZURE_CONTENT_UNDERSTANDING_ENDPOINT", ""),
                api_version=os.getenv(
                    "AZURE_CONTENT_UNDERSTANDING_API_VERSION", "2024-12-01-preview"
                ),
                ai_service_endpoint=os.getenv("AZURE_AI_SERVICE_ENDPOINT", ""),
                ai_service_api_version=os.getenv(
                    "AZURE_AI_SERVICE_API_VERSION", "2024-12-01-preview"
                ),
            ),
            server=ServerSettings(
                a2a_host=os.getenv("A2A_HOST", "FOUNDRY"),
                ui_host=os.getenv("A2A_UI_HOST", "0.0.0.0"),
                ui_port=_load_env_int("A2A_UI_PORT", 12000),
                backend_server_url=os.getenv(
                    "BACKEND_SERVER_URL", "http://localhost:12000"
                ),
                websocket_server_url=os.getenv(
                    "WEBSOCKET_SERVER_URL", "http://localhost:8080"
                ),
                debug_mode=_load_env_bool("DEBUG_MODE", False),
                verbose_logging=_load_env_bool("VERBOSE_LOGGING", False),
            ),
            auth=AuthenticationSettings(
                secret_key=os.getenv("SECRET_KEY", "change-me"),
                jwt_algorithm=os.getenv("JWT_ALGORITHM", "HS256"),
                azure_tenant_id=os.getenv("AZURE_TENANT_ID"),
                azure_client_id=os.getenv("AZURE_CLIENT_ID"),
            ),
            telemetry=TelemetrySettings(
                application_insights_connection_string=os.getenv(
                    "APPLICATIONINSIGHTS_CONNECTION_STRING"
                ),
            ),
            google_adk=GoogleADKSettings(
                api_key=os.getenv("GOOGLE_API_KEY", ""),
                use_vertexai=_load_env_bool("GOOGLE_GENAI_USE_VERTEXAI", False),
            ),
            a2a_behavior=A2ABehaviorSettings(
                include_last_host_turn=_load_env_bool("A2A_INCLUDE_LAST_HOST_TURN", True),
                last_host_turn_max_chars=(
                    _load_env_int("A2A_LAST_HOST_TURN_MAX_CHARS", 0)
                    if os.getenv("A2A_LAST_HOST_TURN_MAX_CHARS")
                    else None
                ),
                last_host_turns=_load_env_int("A2A_LAST_HOST_TURNS", 1),
                memory_summary_max_chars=_load_env_int(
                    "A2A_MEMORY_SUMMARY_MAX_CHARS", 2000
                ),
            ),
        )
        
        _logger.info("Settings loaded successfully")
        return settings
        
    except Exception as e:
        _logger.error(f"Failed to load settings: {e}")
        raise


def get_settings() -> Settings:
    """
    Get or create the settings singleton instance.
    
    Returns the global Settings instance, creating it if necessary.
    Thread-safe singleton pattern ensures configuration is loaded once.
    
    :return: Global Settings instance
    :raises ValueError: If settings cannot be loaded
    """
    global _settings_instance
    
    if _settings_instance is None:
        try:
            _settings_instance = _create_settings()
        except Exception as e:
            _logger.error(f"Critical error initializing settings: {e}")
            raise
    
    return _settings_instance


def reset_settings() -> None:
    """
    Reset the settings singleton (primarily for testing).
    
    Forces settings to be reloaded on next get_settings() call.
    Should only be used in test environments.
    """
    global _settings_instance
    _settings_instance = None
    _logger.debug("Settings instance reset")
