import json

import httpx

from app.chat_cli import ask, parse_events


def sse(*events: tuple[str, dict]) -> bytes:
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events).encode()


def make_client(handler) -> httpx.Client:
    return httpx.Client(base_url="http://app.test", transport=httpx.MockTransport(handler))


def run_ask(handler, **overrides):
    out: list[str] = []
    kwargs = {"thinking": True, "model": None, "show_thinking": True, "write": out.append}
    kwargs.update(overrides)
    with make_client(handler) as client:
        answer = ask(client, [{"role": "user", "content": "hi"}], **kwargs)
    return answer, "".join(out)


DONE = (
    "done",
    {
        "finish_reason": "stop",
        "usage": {"completion_tokens": 7},
        "latency_ms": 1500,
        "ttft_ms": 300,
    },
)


def test_parse_events_handles_multiple_events_and_a_missing_final_blank_line():
    lines = iter(["event: a", 'data: {"x": 1}', "", "event: b", 'data: {"y": 2}'])
    assert list(parse_events(lines)) == [("a", {"x": 1}), ("b", {"y": 2})]


def test_prints_thinking_then_answer_and_returns_only_the_answer():
    body = sse(
        ("meta", {}),
        ("reasoning", {"delta": "17*23"}),
        ("content", {"delta": "391"}),
        DONE,
    )
    answer, printed = run_ask(lambda r: httpx.Response(200, content=body))
    assert answer == "391"
    assert "[thinking]\n17*23" in printed
    assert "[answer]\n391" in printed
    assert "tokens=7 time=1.5s first_token=0.3s" in printed


def test_hidden_thinking_is_not_printed():
    body = sse(("reasoning", {"delta": "secret plan"}), ("content", {"delta": "ok"}), DONE)
    _, printed = run_ask(lambda r: httpx.Response(200, content=body), show_thinking=False)
    assert "secret plan" not in printed
    assert "ok" in printed


def test_the_request_carries_the_flags():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, content=sse(("content", {"delta": "x"}), DONE))

    run_ask(handler, thinking=False, model="gpt-oss")
    assert seen == {
        "messages": [{"role": "user", "content": "hi"}],
        "thinking": False,
        "model": "gpt-oss",
    }


def test_http_errors_are_printed_without_a_traceback():
    body = {"error": {"code": "upstream_busy", "message": "The model is busy."}}
    answer, printed = run_ask(lambda r: httpx.Response(503, json=body))
    assert answer is None
    assert "[error 503]" in printed and "upstream_busy" in printed


def test_stream_errors_are_printed():
    body = sse(
        ("content", {"delta": "Hel"}),
        ("error", {"code": "upstream_interrupted", "message": "lost"}),
    )
    answer, printed = run_ask(lambda r: httpx.Response(200, content=body))
    assert answer is None
    assert "[error] lost (upstream_interrupted)" in printed


def test_app_not_running_gives_a_hint():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    answer, printed = run_ask(handler)
    assert answer is None
    assert "Is it running?" in printed


def test_sources_are_printed_and_a_conversation_path_and_payload_can_be_used():
    seen = {}

    def handler(request):
        seen["path"], seen["body"] = request.url.path, json.loads(request.content)
        return httpx.Response(
            200,
            content=sse(
                (
                    "sources",
                    {
                        "mode": "search",
                        "sources": [{"n": 1, "filename": "a.pdf", "page": 3}],
                        "skipped": [{"filename": "b.pdf", "status": "processing"}],
                    },
                ),
                ("content", {"delta": "see [1]"}),
                DONE,
            ),
        )

    out: list[str] = []
    with make_client(handler) as client:
        answer = ask(
            client,
            [],
            thinking=True,
            model=None,
            show_thinking=True,
            write=out.append,
            path="/api/conversations/c1/messages",
            payload={"content": "q"},
        )
    printed = "".join(out)
    assert answer == "see [1]"
    assert seen == {"path": "/api/conversations/c1/messages", "body": {"content": "q"}}
    assert "[sources] mode=search [1] a.pdf p.3" in printed
    assert "[skipped] b.pdf is processing" in printed
