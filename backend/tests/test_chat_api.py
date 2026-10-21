import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.chat import ChatRequest, ChatService
from app.services.llm import LLMClient
from tests.conftest import BASE

URL = f"{BASE}/chat/completions"


def chunk(delta=None, finish=None, usage=None, empty_choices=False) -> dict:
    return {
        "id": "c1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "qwen3.8",
        "choices": []
        if empty_choices
        else [{"index": 0, "delta": delta or {}, "finish_reason": finish}],
        **({"usage": usage} if usage else {}),
    }


def sse_bytes(*chunks: dict) -> bytes:
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks)
    return (body + "data: [DONE]\n\n").encode()


def sse_response(*chunks: dict) -> httpx.Response:
    return httpx.Response(
        200, content=sse_bytes(*chunks), headers={"content-type": "text/event-stream"}
    )


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.split("\n") if ": " in line)
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def post_chat(settings: Settings, body: dict) -> httpx.Response:
    with TestClient(create_app(settings)) as client:
        return client.post("/api/chat", json=body)


QUESTION = {"messages": [{"role": "user", "content": "What is 17*23?"}]}
USAGE = {"prompt_tokens": 25, "completion_tokens": 42, "total_tokens": 67}


@respx.mock
def test_streams_reasoning_then_answer_then_done(settings):
    respx.post(URL).mock(
        return_value=sse_response(
            chunk({"role": "assistant", "content": ""}),
            chunk({"reasoning_content": "17*20 "}),
            chunk({"reasoning_content": "+ 17*3"}),
            chunk({"content": "\n\n"}),
            chunk({"content": "391"}),
            chunk(finish="stop"),
            chunk(usage=USAGE, empty_choices=True),
        )
    )
    response = post_chat(settings, QUESTION)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = parse_sse(response.text)
    names = [name for name, _ in events]
    assert names == ["meta", "reasoning", "reasoning", "content", "done"]
    assert events[0][1] == {"model": "qwen3.8", "thinking": True, "trimmed_messages": 0}
    assert "".join(d["delta"] for n, d in events if n == "reasoning") == "17*20 + 17*3"
    assert events[3][1] == {"delta": "391"}  # leading blank lines dropped
    done = events[-1][1]
    assert done["finish_reason"] == "stop"
    assert done["usage"] == {"prompt_tokens": 25, "completion_tokens": 42}
    assert done["ttft_ms"] is not None and done["latency_ms"] >= done["ttft_ms"]


@respx.mock
def test_the_upstream_request_is_built_correctly(settings):
    route = respx.post(URL).mock(return_value=sse_response(chunk({"content": "hi"}, "stop")))
    post_chat(settings, QUESTION)
    sent = json.loads(route.calls.last.request.content)
    assert sent["model"] == "qwen3.8"
    assert sent["stream"] is True
    assert sent["stream_options"] == {"include_usage": True}
    assert sent["max_tokens"] == 8192
    assert "chat_template_kwargs" not in sent
    assert sent["messages"] == QUESTION["messages"]
    assert route.calls.last.request.headers["authorization"] == "Bearer sk-test-secret"


@respx.mock
def test_thinking_off_sends_the_template_flag_at_the_top_level(settings):
    route = respx.post(URL).mock(return_value=sse_response(chunk({"content": "391"}, "stop")))
    response = post_chat(settings, {**QUESTION, "thinking": False})
    sent = json.loads(route.calls.last.request.content)
    assert sent["chat_template_kwargs"] == {"enable_thinking": False}
    assert parse_sse(response.text)[0][1]["thinking"] is False


@respx.mock
def test_inline_think_tags_are_split_into_reasoning_and_answer(settings):
    respx.post(URL).mock(
        return_value=sse_response(
            chunk({"content": "<thi"}),
            chunk({"content": "nk>plan it"}),
            chunk({"content": "</think>\n\nThe "}),
            chunk({"content": "answer"}, "stop"),
        )
    )
    events = parse_sse(post_chat(settings, QUESTION).text)
    reasoning = "".join(d["delta"] for n, d in events if n == "reasoning")
    answer = "".join(d["delta"] for n, d in events if n == "content")
    assert (reasoning, answer) == ("plan it", "The answer")


@respx.mock
def test_a_length_stop_is_reported(settings):
    respx.post(URL).mock(return_value=sse_response(chunk({"reasoning_content": "hmm"}, "length")))
    done = parse_sse(post_chat(settings, QUESTION).text)[-1]
    assert done == ("done", {**done[1], "finish_reason": "length"})


@respx.mock
@pytest.mark.parametrize(
    ("upstream", "status", "code"),
    [
        (httpx.Response(401, json={"error": "bad key"}), 502, "upstream_auth"),
        (httpx.Response(429, json={"error": "cooldown"}), 503, "upstream_busy"),
        (httpx.Response(500, json={"error": "boom"}), 502, "upstream_error"),
        (
            httpx.Response(
                400, json={"error": {"message": "maximum context length is 262144 tokens"}}
            ),
            413,
            "context_too_long",
        ),
    ],
)
def test_upstream_failures_before_the_stream_get_a_real_http_status(
    settings, upstream, status, code
):
    respx.post(URL).mock(return_value=upstream)
    response = post_chat(settings, QUESTION)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "sk-test-secret" not in response.text


@respx.mock
def test_unreachable_upstream_gets_a_clean_502(settings):
    respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    response = post_chat(settings, QUESTION)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "upstream_unreachable"


class BreakingStream(httpx.AsyncByteStream):
    """Sends one chunk, then the connection drops."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield f"data: {json.dumps(chunk({'content': 'Hel'}))}\n\n".encode()
        raise httpx.ReadError("connection lost")

    async def aclose(self) -> None:
        pass


@respx.mock
def test_a_connection_lost_mid_stream_becomes_an_error_event(settings):
    respx.post(URL).mock(
        return_value=httpx.Response(
            200, stream=BreakingStream(), headers={"content-type": "text/event-stream"}
        )
    )
    events = parse_sse(post_chat(settings, QUESTION).text)
    assert [n for n, _ in events] == ["meta", "content", "error"]
    assert events[-1][1]["code"] == "upstream_interrupted"


@respx.mock
@pytest.mark.parametrize(
    ("body", "status", "code"),
    [
        ({"messages": []}, 422, None),
        ({"messages": [{"role": "robot", "content": "hi"}]}, 422, None),
        ({"messages": [{"role": "user", "content": ""}]}, 422, None),
        (
            {"messages": [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]},
            400,
            "invalid_messages",
        ),
        ({**QUESTION, "model": "not-enabled"}, 400, "model_not_allowed"),
    ],
)
def test_invalid_requests_never_reach_the_model(settings, body, status, code):
    route = respx.post(URL).mock(return_value=sse_response(chunk({"content": "x"}, "stop")))
    response = post_chat(settings, body)
    assert response.status_code == status
    if code:
        assert response.json()["error"]["code"] == code
    assert route.call_count == 0


@respx.mock
def test_old_messages_are_trimmed_to_the_budget(tmp_path):
    small = Settings(
        _env_file=None,
        litellm_base_url=BASE,
        litellm_api_key="sk-test",
        data_dir=tmp_path,
        max_retries=0,
        context_budget_tokens=1500,
        max_output_tokens=512,
    )
    route = respx.post(URL).mock(return_value=sse_response(chunk({"content": "ok"}, "stop")))
    history = [{"role": "system", "content": "Be brief."}]
    for i in range(6):
        history.append({"role": "user", "content": f"question {i} " + "x" * 900})
        history.append({"role": "assistant", "content": f"answer {i} " + "y" * 900})
    history.append({"role": "user", "content": "final question"})
    events = parse_sse(post_chat(small, {"messages": history}).text)
    sent = json.loads(route.calls.last.request.content)["messages"]
    assert events[0][1]["trimmed_messages"] == len(history) - len(sent) > 0
    assert sent[0] == history[0]
    assert sent[-1] == history[-1]


async def test_closing_the_event_stream_closes_the_upstream_connection(settings):
    closed = asyncio.Event()

    class TrackingStream(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            for word in ["one", "two", "three", "four"]:
                yield f"data: {json.dumps(chunk({'content': word + ' '}))}\n\n".encode()
                await asyncio.sleep(0)

        async def aclose(self) -> None:
            closed.set()

    with respx.mock:
        respx.post(URL).mock(
            return_value=httpx.Response(
                200, stream=TrackingStream(), headers={"content-type": "text/event-stream"}
            )
        )
        llm = LLMClient(settings)
        service = ChatService(llm, settings)
        prepared = service.prepare(ChatRequest(messages=QUESTION["messages"]))
        stream = await service.open_stream(prepared)
        events = service.events(prepared, stream)
        assert (await events.__anext__())[0] == "meta"
        assert (await events.__anext__())[0] == "content"
        await events.aclose()  # what happens when the browser disconnects
        await llm.aclose()
    assert closed.is_set()
