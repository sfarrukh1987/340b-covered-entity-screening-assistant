"""Black-box tests for A1 Parse HTML in the 340B screening workflow.

Protocol: Beautiful Soup 4, beautifulsoup4==4.14.3.
Source: https://www.crummy.com/software/BeautifulSoup/bs4/doc/api/bs4.html
Release: https://pypi.org/project/beautifulsoup4/4.14.3/
Contract: saved HTML (str) -> extracted text (str).
Exact interface: BeautifulSoup(html, "html.parser").get_text(" ", strip=True).
Environment: CPython 3.12.14; pytest==8.3.5; soupsieve==3.0.3;
typing_extensions==4.16.0. Complete dependency pins are in requirements.txt.
Inputs are invented and contain no patient information. No network or LLM calls.
"""

import pytest
from bs4 import BeautifulSoup


# Typical inputs
def test_service_text():
    out = BeautifulSoup(
        "<h1>Example Health</h1><p>Primary care</p>", "html.parser"
    ).get_text(" ", strip=True)
    assert isinstance(out, str)
    assert out == "Example Health Primary care"


def test_nested_text():
    out = BeautifulSoup(
        "<p>Primary <b>care</b></p><p>Dental</p>", "html.parser"
    ).get_text(" ", strip=True)
    assert out == "Primary care Dental"


def test_whitespace():
    out = BeautifulSoup(
        "<p> Primary care </p>\n<p> Dental </p>", "html.parser"
    ).get_text(" ", strip=True)
    assert out == "Primary care Dental"


def test_entities():
    out = BeautifulSoup(
        "<p>Care &amp; support &#233;</p>", "html.parser"
    ).get_text(" ", strip=True)
    assert out == "Care & support \u00e9"


def test_noise():
    out = BeautifulSoup(
        "<p>Primary care</p><script>hidden()</script>"
        "<style>p{color:red}</style><template>template text</template>"
        "<!--comment-->",
        "html.parser",
    ).get_text(" ", strip=True)
    assert out == "Primary care"


# Edge cases
@pytest.mark.parametrize("html", ["", " \n\t", "<div></div>"],
                         ids=["empty", "whitespace", "empty_tag"])
def test_empty_text(html):
    out = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    assert isinstance(out, str)
    assert out == ""


def test_plain_text():
    out = BeautifulSoup("Primary care", "html.parser").get_text(" ", strip=True)
    assert out == "Primary care"


def test_malformed_html():
    out = BeautifulSoup(
        "<div><p>Primary care", "html.parser"
    ).get_text(" ", strip=True)
    assert out == "Primary care"


def test_unicode():
    out = BeautifulSoup(
        "<p>Atenci\u00f3n primaria</p><p>\u521d\u7ea7\u4fdd\u5065</p>",
        "html.parser",
    ).get_text(" ", strip=True)
    assert out == "Atenci\u00f3n primaria \u521d\u7ea7\u4fdd\u5065"


def test_long_page():
    out = BeautifulSoup(
        "<p>Care</p>" * 1000, "html.parser"
    ).get_text(" ", strip=True)
    assert out == " ".join(["Care"] * 1000)


def test_dynamic_only_page():
    # This checks the actual limit, not a promise to render JavaScript.
    out = BeautifulSoup(
        '<div id="app"></div><script>document.write("Primary care")</script>',
        "html.parser",
    ).get_text(" ", strip=True)
    assert out == ""


def test_navigation_is_retained():
    # Parsing succeeds even though navigation still requires human review.
    out = BeautifulSoup(
        "<nav>Home Services</nav><main><p>Primary care</p></main>",
        "html.parser",
    ).get_text(" ", strip=True)
    assert out == "Home Services Primary care"


# Invalid inputs
@pytest.mark.parametrize("bad_input", [None, 42, 3.5, True, []],
                         ids=["none", "integer", "float", "boolean", "list"])
def test_input_types(bad_input):
    # The exact exception for these values is observed in the pinned release;
    # its public documentation does not promise a universal exception type.
    with pytest.raises(TypeError):
        BeautifulSoup(bad_input, "html.parser").get_text(" ", strip=True)
