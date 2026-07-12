import pytest

from tripper.config import ConfigError, Settings


def test_defaults_are_keyless() -> None:
    s = Settings(_env_file=None)
    assert s.enabled_providers == ["mock"]
    assert s.scorer == "heuristic"
    assert s.agent_env()["ENABLED_PROVIDERS"] == "mock"


def test_providers_split_from_string() -> None:
    s = Settings(_env_file=None, enabled_providers="mock, liteapi", liteapi_api_key="sand_x")
    assert s.enabled_providers == ["mock", "liteapi"]
    assert s.agent_env()["LITEAPI_API_KEY"] == "sand_x"


def test_liteapi_requires_key() -> None:
    with pytest.raises(ConfigError):
        Settings(_env_file=None, enabled_providers=["liteapi"])


def test_llm_scorer_requires_transport() -> None:
    with pytest.raises(ConfigError):
        Settings(_env_file=None, scorer="llm")


def test_llm_scorer_ok_with_endpoint() -> None:
    s = Settings(_env_file=None, scorer="llm", nebius_endpoint_url="https://endpoint.example/")
    assert "NEBIUS_ENDPOINT_URL" in s.agent_env()
