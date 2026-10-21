from app.services.chunking import chunk_pages
from app.services.extract import Page
from app.services.tokens import ApproxTokenCounter

COUNT = ApproxTokenCounter().count


def paragraphs(n: int, words: int = 30) -> str:
    return "\n\n".join(" ".join(f"w{i}x{j}" for j in range(words)) + "." for i in range(n))


def test_short_text_is_one_chunk():
    chunks = chunk_pages([Page(None, "A short note.")])
    assert [(c.ordinal, c.page, c.text) for c in chunks] == [(0, None, "A short note.")]


def test_chunks_respect_the_target_and_overlap():
    chunks = chunk_pages(
        [Page(None, paragraphs(40, words=10))], target_tokens=200, overlap_tokens=25
    )
    assert len(chunks) > 3
    assert all(c.tokens <= 200 for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    first, second = chunks[0].text.split("\n\n"), chunks[1].text.split("\n\n")
    assert second[0] == first[-1]  # the last paragraph is repeated at the start of the next chunk


def test_every_paragraph_is_in_some_chunk_and_nothing_is_repeated_at_the_end():
    text = paragraphs(25)
    chunks = chunk_pages([Page(None, text)], target_tokens=150, overlap_tokens=40)
    joined = "\n\n".join(c.text for c in chunks)
    assert all(p in joined for p in text.split("\n\n"))
    assert chunks[-1].text != chunks[-2].text
    assert chunks[-1].text.split("\n\n")[-1] == text.split("\n\n")[-1]


def test_a_huge_paragraph_is_split():
    text = " ".join(f"Sentence number {i} is here." for i in range(400))
    chunks = chunk_pages([Page(None, text)], target_tokens=100, overlap_tokens=0)
    assert len(chunks) > 5 and all(c.tokens <= 100 for c in chunks)


def test_text_without_any_break_is_still_split():
    chunks = chunk_pages([Page(None, "x" * 5000)], target_tokens=100, overlap_tokens=0)
    assert len(chunks) > 5 and all(COUNT(c.text) <= 100 for c in chunks)


def test_chunks_remember_the_page_where_they_start():
    pages = [Page(1, paragraphs(1)), Page(2, paragraphs(1)), Page(3, "Last page.")]
    chunks = chunk_pages(pages, target_tokens=100, overlap_tokens=0)
    assert [c.page for c in chunks] == [1, 2]  # the short last page joins the chunk before it
    assert "Last page." in chunks[-1].text


def test_empty_pages_give_no_chunks():
    assert chunk_pages([Page(1, ""), Page(2, "")]) == []
