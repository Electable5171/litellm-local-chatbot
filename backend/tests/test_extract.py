import pytest

from app.errors import ApiError
from app.services.extract import extract
from tests.files import make_docx, make_pdf


def test_text_and_markdown_are_read_and_cleaned():
    result = extract("notes.md", b"# Title\r\n\r\n\r\n\r\nBody   text")
    assert result.pages[0].number is None
    assert result.pages[0].text == "# Title\n\nBody text"
    assert result.mime == "text/markdown"


def test_windows_1252_text_is_not_garbled():
    assert extract("a.txt", "caf\xe9".encode("cp1252")).pages[0].text == "café"


def test_pdf_pages_keep_their_numbers():
    result = extract("report.pdf", make_pdf(["First page text", "Second (page) text"]))
    assert [(p.number, p.text) for p in result.pages] == [
        (1, "First page text"),
        (2, "Second (page) text"),
    ]
    assert result.page_count == 2


def test_pdf_without_text_says_it_may_be_a_scan():
    with pytest.raises(ApiError) as caught:
        extract("scan.pdf", make_pdf(["", ""]))
    assert caught.value.code == "no_text" and "scan" in caught.value.message


def test_pdf_page_limit():
    with pytest.raises(ApiError) as caught:
        extract("big.pdf", make_pdf(["a", "b", "c"]), max_pdf_pages=2)
    assert caught.value.code == "document_too_large"


def test_docx_paragraphs_are_read():
    result = extract("memo.docx", make_docx(["One", "Two"]))
    assert result.pages[0].text == "One\n\nTwo"


@pytest.mark.parametrize(
    ("name", "data", "code"),
    [
        ("sheet.xlsx", b"PK", "unsupported_file"),
        ("noext", b"hello", "unsupported_file"),
        ("fake.pdf", b"just text", "unreadable_file"),
        ("broken.pdf", b"%PDF-1.4\ngarbage", "unreadable_file"),
        ("fake.docx", b"just text", "unreadable_file"),
        ("broken.docx", b"PK\x03\x04nonsense", "unreadable_file"),
        ("binary.txt", b"abc\x00\x01\x02", "unreadable_file"),
        ("empty.txt", b"   \n  ", "no_text"),
    ],
)
def test_unusable_files_get_a_clear_error(name, data, code):
    with pytest.raises(ApiError) as caught:
        extract(name, data)
    assert caught.value.code == code
