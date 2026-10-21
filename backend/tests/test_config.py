import pytest
from pydantic import ValidationError

from app.__main__ import main
from app.config import Settings, get_settings


@pytest.mark.parametrize(
    "given",
    [
        "http://h:4000",
        "http://h:4000/",
        "http://h:4000/v1",
        "http://h:4000/v1/",
        "  http://h:4000/v1  ",
    ],
)
def test_base_url_is_normalised(given):
    s = Settings(_env_file=None, litellm_base_url=given, litellm_api_key="k")
    assert s.litellm_base_url == "http://h:4000/v1"


def test_base_url_needs_a_scheme():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, litellm_base_url="h:4000", litellm_api_key="k")


def test_api_key_is_required(monkeypatch):
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_api_key_never_appears_in_repr():
    s = Settings(_env_file=None, litellm_api_key="sk-very-secret")
    assert "sk-very-secret" not in repr(s)
    assert "sk-very-secret" not in str(s)


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.5", "example.com"])  # noqa: S104
def test_non_loopback_host_is_refused(host):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, litellm_api_key="k", host=host)


def test_model_choices_default_and_parsing():
    only_chat = Settings(_env_file=None, litellm_api_key="k", chat_model="qwen3.8")
    assert only_chat.model_choices == ["qwen3.8"]
    several = Settings(_env_file=None, litellm_api_key="k", allowed_models=" a , b,,c ")
    assert several.model_choices == ["a", "b", "c"]


def test_main_prints_a_clear_message_when_the_key_is_missing(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.delenv("LITELLM_API_KEY", raising=False)
    get_settings.cache_clear()
    with pytest.raises(SystemExit) as exit_info:
        main()
    assert exit_info.value.code == 2
    assert "LITELLM_API_KEY" in capsys.readouterr().err
    get_settings.cache_clear()
