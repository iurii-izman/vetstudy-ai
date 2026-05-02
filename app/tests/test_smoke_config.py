from app.config import Settings


def test_settings_smoke():
    settings = Settings()
    assert isinstance(settings.app_name, str)
    assert isinstance(settings.allowed_user_ids, set)
    assert settings.daily_cost_limit_usd >= 0
    assert settings.monthly_cost_limit_usd >= 0
