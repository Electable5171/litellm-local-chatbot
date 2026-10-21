"""Command-line chat client for the local app (the web UI comes later).

    python -m app.chat_cli "What is 17*23?"
    python -m app.chat_cli --no-think "Say hi"
    python -m app.chat_cli -i                  # interactive, keeps the conversation

The app must be running (scripts\\run.cmd). The model's thinking is shown live under [thinking].
"""

import argparse
import json
import os
import sys
from collections.abc import Callable, Iterator

import httpx


def parse_events(lines: Iterator[str]) -> Iterator[tuple[str, dict]]:
    """Parse server-sent events: 'event: x' + 'data: {...}' + blank line."""
    event, data = "message", []
    for line in lines:
        if line == "":
            if data:
                yield event, json.loads("\n".join(data))
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip())
    if data:
        yield event, json.loads("\n".join(data))


def ask(
    client: httpx.Client,
    messages: list[dict[str, str]],
    *,
    thinking: bool,
    model: str | None,
    show_thinking: bool,
    write: Callable[[str], None],
) -> str | None:
    """Send one question, print the streamed answer, return the answer text (None on failure)."""
    payload: dict = {"messages": messages, "thinking": thinking}
    if model:
        payload["model"] = model
    answer: list[str] = []
    section = None
    try:
        with client.stream("POST", "/api/chat", json=payload) as response:
            if response.status_code != 200:
                body = json.loads(response.read() or b"{}")
                error = body.get("error", body.get("detail", body))
                write(f"[error {response.status_code}] {json.dumps(error, ensure_ascii=False)}\n")
                return None
            for name, data in parse_events(response.iter_lines()):
                if name in ("reasoning", "content"):
                    if name == "reasoning" and not show_thinking:
                        continue
                    if section != name:
                        write(f"\n[{'thinking' if name == 'reasoning' else 'answer'}]\n")
                        section = name
                    write(data["delta"])
                    if name == "content":
                        answer.append(data["delta"])
                elif name == "error":
                    write(f"\n[error] {data.get('message')} ({data.get('code')})\n")
                    return None
                elif name == "done":
                    usage = data.get("usage") or {}
                    ttft = data.get("ttft_ms")
                    write(
                        f"\n\n[done] finish={data.get('finish_reason')} "
                        f"tokens={usage.get('completion_tokens')} "
                        f"time={data['latency_ms'] / 1000:.1f}s "
                        f"first_token={'-' if ttft is None else f'{ttft / 1000:.1f}s'}\n"
                    )
    except httpx.ConnectError:
        write("Cannot reach the app. Is it running? Start it with scripts\\run.cmd\n")
        return None
    return "".join(answer)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chat_cli", description=__doc__.split("\n\n")[0])
    parser.add_argument("prompt", nargs="*", help="the question (omit with -i)")
    parser.add_argument("-i", "--interactive", action="store_true", help="keep a conversation")
    parser.add_argument("--no-think", action="store_true", help="switch the model's thinking off")
    parser.add_argument("--hide-thinking", action="store_true", help="do not print the thinking")
    parser.add_argument("--model", help="model id (default: the app's chat model)")
    parser.add_argument("--system", help="a system prompt")
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '8000')}")
    args = parser.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def write(text: str) -> None:
        sys.stdout.write(text)
        sys.stdout.flush()

    history: list[dict[str, str]] = []
    if args.system:
        history.append({"role": "system", "content": args.system})
    first = " ".join(args.prompt).strip()
    if not first and not args.interactive:
        parser.error("give a question, or use -i")

    timeout = httpx.Timeout(10.0, read=600.0)  # long thinking pauses are normal
    with httpx.Client(base_url=args.url, timeout=timeout, trust_env=False) as client:
        question = first
        while True:
            if not question:
                try:
                    question = input("\nyou> ").strip()
                except EOFError:
                    return 0
                if question in ("/quit", "/exit"):
                    return 0
                if question == "/new":
                    history = history[:1] if args.system else []
                    question = ""
                    continue
                if not question:
                    continue
            history.append({"role": "user", "content": question})
            answer = ask(
                client,
                history,
                thinking=not args.no_think,
                model=args.model,
                show_thinking=not args.hide_thinking,
                write=write,
            )
            if answer is None:
                return 1
            history.append({"role": "assistant", "content": answer})
            if not args.interactive:
                return 0
            question = ""


if __name__ == "__main__":
    raise SystemExit(main())
