"""Tests for carto.domain.config."""

from carto.domain.config import CartoConfig, LLMConfig


def test_default_config():
    config = CartoConfig()
    assert config.target_url is None
    assert config.llm.provider == "openai"
    assert config.llm.model is None
    assert config.orchestra.max_steps == 50


def test_parse_json():
    json_data = """
    {
        "target_url": "https://example.com",
        "llm": {
            "provider": "anthropic",
            "model": "claude-3",
            "base_url": "https://custom.api.com"
        },
        "auth": {
            "role_name": "admin"
        },
        "orchestra": {
            "headless": false
        }
    }
    """
    config = CartoConfig.model_validate_json(json_data)
    assert config.target_url == "https://example.com"
    assert config.llm.provider == "anthropic"
    assert config.llm.base_url == "https://custom.api.com"
    assert config.llm.api_key_env == "OPENAI_API_KEY"  # default
    assert config.auth.role_name == "admin"
    assert config.auth.role_password is None
    assert config.orchestra.headless is False
    assert config.orchestra.max_steps == 50


def test_extra_fields_ignored():
    json_data = """
    {
        "target_url": "https://example.com",
        "unknown_field": "123",
        "llm": {
            "provider": "openai",
            "unknown_model_field": true
        }
    }
    """
    config = CartoConfig.model_validate_json(json_data)
    assert config.target_url == "https://example.com"
    assert config.llm.provider == "openai"
    # Should not raise validation error due to extra="ignore"
