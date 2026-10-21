import pytest

from app.services.thinking import Piece, ThinkingParser


def run(chunks: list[tuple[str | None, str | None]]) -> tuple[str, str]:
    """Feed (reasoning, content) chunks; return the joined reasoning and answer text."""
    parser = ThinkingParser()
    pieces: list[Piece] = []
    for reasoning, content in chunks:
        pieces += parser.feed(reasoning, content)
    pieces += parser.flush()
    reasoning_text = "".join(p.text for p in pieces if p.kind == "reasoning")
    content_text = "".join(p.text for p in pieces if p.kind == "content")
    return reasoning_text, content_text


def test_separate_reasoning_field_passes_through():
    assert run([("think ", None), ("more", None), (None, "\n\nThe answer")]) == (
        "think more",
        "The answer",
    )


def test_inline_think_tags():
    assert run([(None, "<think>step one</think>\n\nThe answer")]) == ("step one", "The answer")


@pytest.mark.parametrize("cut", range(1, len("<think>step one</think>\n\nThe answer")))
def test_tags_split_at_every_position(cut):
    text = "<think>step one</think>\n\nThe answer"
    assert run([(None, text[:cut]), (None, text[cut:])]) == ("step one", "The answer")


def test_one_character_at_a_time():
    text = "Before <think>a < b</think> after"
    assert run([(None, ch) for ch in text]) == ("a < b", "Before  after")


def test_text_that_only_looks_like_a_tag_is_kept():
    assert run([(None, "1 < 2 and <thin"), (None, "g> is not a tag")]) == (
        "",
        "1 < 2 and <thing> is not a tag",
    )


def test_a_dangling_partial_tag_is_released_at_the_end():
    assert run([(None, "Answer <thi")]) == ("", "Answer <thi")


def test_unclosed_think_block_counts_as_reasoning():
    assert run([(None, "<think>still thinking")]) == ("still thinking", "")


def test_several_think_blocks():
    text = "<think>one</think>A<think>two</think>B"
    assert run([(None, text)]) == ("onetwo", "AB")


def test_reasoning_and_content_in_the_same_chunk():
    parser = ThinkingParser()
    pieces = parser.feed("why", "answer")
    assert [(p.kind, p.text) for p in pieces] == [("reasoning", "why"), ("content", "answer")]


def test_leading_blank_lines_are_dropped_but_inner_ones_kept():
    assert run([(None, "\n\nline one\n\nline two")]) == ("", "line one\n\nline two")


def test_whitespace_only_chunks_at_the_start_are_ignored():
    assert run([(None, "\n"), (None, "\n"), (None, "Hi")]) == ("", "Hi")
