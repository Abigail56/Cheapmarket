import pytest
from pydantic import ValidationError

from app.core.config import Settings

SAFE_PRODUCTION = {
    "ENVIRONMENT": "production", "DEBUG": False, "SECRET_KEY": "s" * 48,
    "PUBLIC_BASE_URL": "https://api.example.com", "REDIS_PASSWORD": "redis-password",
    "POSTGRES_USER": "u", "POSTGRES_PASSWORD": "p", "POSTGRES_DB": "d",
}


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **{**SAFE_PRODUCTION, **overrides})  # type: ignore[call-arg]


def test_safe_production_settings_start():
    assert make().ENVIRONMENT == "production"


@pytest.mark.parametrize("override, message", [
    ({"SECRET_KEY": "change-me"}, "SECRET_KEY"),
    ({"SECRET_KEY": "short"}, "SECRET_KEY"),
    ({"DEBUG": True}, "DEBUG"),
    ({"PUBLIC_BASE_URL": "http://api.example.com"}, "PUBLIC_BASE_URL"),
    ({"REDIS_PASSWORD": None}, "REDIS_PASSWORD"),
])
def test_unsafe_production_settings_refuse_to_start(override, message):
    with pytest.raises(ValidationError, match=message):
        make(**override)


def test_local_allows_development_settings():
    s = make(ENVIRONMENT="local", DEBUG=True, SECRET_KEY="change-me",
             PUBLIC_BASE_URL="http://localhost:8000", REDIS_PASSWORD=None)
    assert s.DEBUG
