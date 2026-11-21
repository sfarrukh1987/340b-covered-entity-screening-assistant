"""A1: the Session 6 parser and a separate service-scope view."""

from bs4 import BeautifulSoup


def parse_html(html: str) -> str:
    return BeautifulSoup(html, "html.parser").get_text(" ", strip=True)


def service_section(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in reversed(soup.select("nav, header, footer, [role=navigation]")):
        element.decompose()
    body = soup.find("main") or soup.find("body") or soup
    return body.get_text(" ", strip=True)
