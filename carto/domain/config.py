"""
Configuration models for Carto.

Provides a structured way to load execution parameters from a JSON/YAML file,
acting as an alternative to passing dozens of CLI arguments.
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class LLMConfig(BaseModel):
    """LLM provider and model configuration."""

    provider: str = Field(default="openai", description="openai, anthropic, gemini")
    model: Optional[str] = Field(default=None, description="Model identifier")
    api_key_env: str = Field(default="OPENAI_API_KEY", description="Environment variable holding the API key")
    api_key: Optional[str] = Field(default=None, description="Explicit API key (overrides env var)")
    base_url: Optional[str] = Field(default=None, description="Custom base URL (e.g., for Qwen, Ollama, vLLM)")


class AuthConfig(BaseModel):
    """Authentication configuration for a single role run."""

    role_name: Optional[str] = Field(default=None, description="Logical name of the role (e.g., admin)")
    role_username: Optional[str] = Field(default=None, description="Login username")
    role_password: Optional[str] = Field(default=None, description="Login password")


class OrchestratorConfigOverrides(BaseModel):
    """Overrides for orchestrator parameters."""

    max_steps: int = Field(default=50)
    headless: bool = Field(default=True)
    screenshot_each_step: bool = Field(default=False)
    approval_mode: str = Field(default="auto", description="auto, cli")


class CartoConfig(BaseModel):
    """
    Root configuration object for a Carto run.
    Can be loaded from a JSON file.
    """

    model_config = ConfigDict(extra="ignore")

    target_url: Optional[str] = Field(default=None, description="Target URL to map")
    llm: LLMConfig = Field(default_factory=LLMConfig)
    auth: AuthConfig = Field(default_factory=AuthConfig)
    orchestra: OrchestratorConfigOverrides = Field(default_factory=OrchestratorConfigOverrides)

    # Output paths
    output_dir: str = Field(default="/tmp/carto/output")
    screenshot_dir: str = Field(default="/tmp/carto/screenshots")
