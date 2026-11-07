"""The paragraph rule (D50) — and the two real manuscripts that motivated it."""

import pytest

from app import prose

# ch-00 as it is actually written: blank-line paragraphs, one of them wrapped across lines
BLANK_STYLE = """# INTRODUCTION

In the end of Titan war, Percy managed to save Luke's life as he is innocent
and captures Kronos essence in his own body.

Then the goddess appeared to him and placed her index finger on his forehead
and sent a blast containing details of his fake identity's family.
"""

# ch-01 as it is actually written: one line per paragraph, no blank lines at all
LINE_STYLE = """# THE BOY WHO LIVED

Mr. and Mrs. Dursley, of number four, Privet Drive, were proud to say that they were perfectly normal.
Mr. Dursley was the director of a firm called Grunnings, which made drills.
Mrs. Dursley was thin and blonde and had nearly twice the usual amount of neck.
The Dursleys had a small son called Dudley and in their opinion there was no finer boy anywhere.
None of them noticed a large, tawny owl flutter past the window.
"""


def test_blank_line_style_keeps_wrapped_lines_inside_their_paragraph():
    blocks = prose.split_paragraphs(BLANK_STYLE)
    assert len(blocks) == 3, blocks          # heading + two paragraphs
    assert blocks[0] == "# INTRODUCTION"
    assert blocks[1].count("\n") == 1        # the wrap stayed inside the paragraph
    assert blocks[2].startswith("Then the goddess")


def test_line_style_gives_every_line_its_own_paragraph():
    """This is the bug the author reported: one blank line (under the title) used to make
    the whole chapter a single paragraph, so paragraph spacing never appeared."""
    blocks = prose.split_paragraphs(LINE_STYLE)
    assert len(blocks) == 6, blocks
    assert blocks[0] == "# THE BOY WHO LIVED"
    assert blocks[1].startswith("Mr. and Mrs. Dursley")
    assert blocks[-1].startswith("None of them noticed")


def test_the_blank_line_under_the_title_does_not_decide_the_style():
    assert prose.is_blank_separated(LINE_STYLE) is False
    assert prose.is_blank_separated(BLANK_STYLE) is True


def test_blank_lines_are_always_a_break():
    text = "one\n\n\ntwo\n\nthree"
    assert prose.split_paragraphs(text) == ["one", "two", "three"]


def test_a_heading_never_swallows_the_prose_beside_it():
    assert prose.split_paragraphs("# Title\nprose right after") == ["# Title", "prose right after"]
    assert prose.split_paragraphs("## Chapter\n> a quote\nmore prose") == [
        "## Chapter", "> a quote", "more prose"]


def test_blockquotes_keep_their_lines_together():
    text = "> first line of the quote\n> second line of the quote\n\nprose after"
    blocks = prose.split_paragraphs(text)
    assert blocks[0].count("\n") == 1 and blocks[1] == "prose after"


def test_carriage_returns_and_trailing_whitespace_are_tolerated():
    text = "# T\r\n\r\nline one   \r\nline two\r\n"
    assert prose.split_paragraphs(text) == ["# T", "line one", "line two"]


def test_empty_and_whitespace_only_input():
    assert prose.split_paragraphs("") == []
    assert prose.split_paragraphs("\n\n   \n") == []


def test_a_single_paragraph_written_on_one_line():
    assert prose.split_paragraphs("Just one line of prose.") == ["Just one line of prose."]


@pytest.mark.parametrize("text,expected", [
    ("a\nb", 2),                 # line style
    ("a\n\nb", 2),               # blank style
    ("a\nb\n\nc\nd", 2),         # mixed: blank lines win, so wraps stay wraps
])
def test_mixed_documents_take_the_blank_line_as_the_break(text, expected):
    assert len(prose.split_paragraphs(text)) == expected


def test_the_epub_gets_paragraphs_not_one_wall_of_text():
    """The same bug was live in the export: ch-01's EPUB was a single <p> with <br/>s."""
    from app import epub
    html = epub._md_to_html(LINE_STYLE)
    assert html.count("<p>") == 5, html
    assert "<h1>" in html
    assert html.count("<br/>") == 0, "line-separated prose is paragraphs, not breaks"
