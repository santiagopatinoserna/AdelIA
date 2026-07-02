from adelia.config import settings


def test_agent_settings_exist():
    assert hasattr(settings, "anthropic_api_key")
    assert hasattr(settings, "agent_model")
    assert settings.agent_model  # non-empty default
