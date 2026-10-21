import pytest

from app.errors import ApiError
from app.services.tokens import ApproxTokenCounter, fit_to_budget

counter = ApproxTokenCounter()


def msg(role: str, size: int) -> dict[str, str]:
    return {"role": role, "content": "x" * size}


def test_counter_leans_high():
    assert counter.count("") == 0
    assert counter.count("x" * 30) == 10  # 3 characters per token
    assert counter.count("ह" * 10) == 10  # non-ASCII: one token per character


def test_everything_fits_nothing_is_dropped():
    messages = [msg("user", 30), msg("assistant", 30), msg("user", 30)]
    kept, dropped = fit_to_budget(messages, 1000, counter)
    assert kept == messages
    assert dropped == 0


def test_oldest_messages_are_dropped_first_and_system_is_kept():
    messages = [
        msg("system", 30),
        msg("user", 300),
        msg("assistant", 300),
        msg("user", 300),
        msg("assistant", 300),
        msg("user", 30),
    ]
    kept, dropped = fit_to_budget(messages, 250, counter)
    assert kept[0]["role"] == "system"
    assert kept[-1] == messages[-1]
    assert dropped == 2
    assert kept == [messages[0], messages[3], messages[4], messages[5]]


def test_the_newest_message_alone_too_big_is_rejected():
    with pytest.raises(ApiError) as error:
        fit_to_budget([msg("user", 3000)], 500, counter)
    assert error.value.code == "context_too_long"
    assert error.value.status == 413


def test_system_prompt_plus_last_message_too_big_is_rejected():
    messages = [msg("system", 3000), msg("user", 30)]
    with pytest.raises(ApiError):
        fit_to_budget(messages, 500, counter)
