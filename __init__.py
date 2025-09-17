"""
bravepython — tiny wrapper around Brave Search's public HTML endpoint.
No API key required.  Scrapes the results page and yields links (or rich
SearchResult objects) just like the duckduckgopython / bingpython helpers.
"""
from __future__ import annotations

import random
import re
from time import sleep
from typing import Iterable, Optional

import requests
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, parse_qs

# --------------------------------------------------------------------------- #
#  Random User-Agent (same logic you used before)
# --------------------------------------------------------------------------- #
def get_useragent() -> str:
    lynx = f"Lynx/{random.randint(2, 3)}.{random.randint(8, 9)}.{random.randint(0, 2)}"
    libwww = f"libwww-FM/{random.randint(2, 3)}.{random.randint(13, 15)}"
    ssl_mm = f"SSL-MM/{random.randint(1, 2)}.{random.randint(3, 5)}"
    openssl = f"OpenSSL/{random.randint(1, 3)}.{random.randint(0, 4)}.{random.randint(0, 9)}"
    return f"{lynx} {libwww} {ssl_mm} {openssl}"


# --------------------------------------------------------------------------- #
#  Low-level request
# --------------------------------------------------------------------------- #
_SAFE_MAP = {"off": "off", "moderate": "moderate", "strict": "strict"}


def _req(
    term: str,
    offset: int = 0,             # 0, 10, 20 …
    count: int = 10,             # Brave supports 10-20 per page on HTML
    lang: str = "en",
    safe: str = "moderate",
    proxies: Optional[dict] = None,
    timeout: int = 10,
    ssl_verify: bool = True,
) -> requests.Response:
    params = {
        "q": term,
        "source": "web",
        "offset": offset,
        "count": count,
        "lang": lang.lower(),
        "safesearch": _SAFE_MAP.get(str(safe).lower(), "moderate"),
    }

    headers = {
        "User-Agent": get_useragent(),
        "Accept": "text/html,application/xhtml+xml",
    }

    resp = requests.get(
        "https://search.brave.com/search",
        params=params,
        headers=headers,
        proxies=proxies,
        timeout=timeout,
        verify=ssl_verify,
    )
    resp.raise_for_status()
    return resp


# --------------------------------------------------------------------------- #
#  Container for a single hit
# --------------------------------------------------------------------------- #
class SearchResult:
    def __init__(self, url: str, title: str, description: str, response: requests.Response):
        self.url = url
        self.title = title
        self.description = description
        self.response = response

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"SearchResult(url={self.url}, "
            f"title={self.title}, "
            f"description={self.description}, "
            f"response={self.response})"
        )


# --------------------------------------------------------------------------- #
#  High-level generator
# --------------------------------------------------------------------------- #
def search(
    term: str,
    num_results: int = 10,
    lang: str = "en",
    proxy: Optional[str] = None,
    safe: str = "moderate",
    advanced: bool = False,
    sleep_interval: float = 0,
    timeout: int = 10,
    ssl_verify: bool = True,
    start_num: int = 0,
    unique: bool = False,
) -> Iterable[str] | Iterable[SearchResult]:
    """
    Yield *num_results* Brave Search links (or rich objects if `advanced=True`).

    Example
    -------
    >>> for url in brave.search("brave search api", 15):
    ...     print(url)
    """
    proxies = (
        {"http": proxy, "https": proxy}
        if proxy and proxy.startswith(("http://", "https://"))
        else None
    )

    fetched = 0
    seen: set[str] = set()
    offset = start_num  # Brave paging offset

    while fetched < num_results:
        resp = _req(
            term=term,
            offset=offset,
            count=10,
            lang=lang,
            safe=safe,
            proxies=proxies,
            timeout=timeout,
            ssl_verify=ssl_verify,
        )

        soup = BeautifulSoup(resp.text, "html.parser")
        # Each organic hit lives in <div class="snippet"> (ads/news have other classes)
        snippets = soup.select("div.snippet")

        if not snippets:  # no more results
            break

        for snip in snippets:
            a = snip.select_one("a")  # first anchor inside snippet
            if not a:
                continue

            raw_link: str = a["href"]
            url = _unwrap_brave_redirect(raw_link)

            if unique and url in seen:
                continue
            seen.add(url)

            title = a.get_text(" ", strip=True)
            desc_tag = snip.select_one(".snippet-content, p")
            desc = desc_tag.get_text(" ", strip=True) if desc_tag else ""

            fetched += 1
            if advanced:
                yield SearchResult(url, title, desc, resp)
            else:
                yield url

            if fetched >= num_results:
                break

        offset += 10  # next page
        sleep(sleep_interval)


# --------------------------------------------------------------------------- #
#  Redirect stripping helper (Brave puts some links behind /link/ tracking)
# --------------------------------------------------------------------------- #
_REDIRECT_RE = re.compile(r"https?://search\.brave\.com/redirect")


def _unwrap_brave_redirect(link: str) -> str:
    if not _REDIRECT_RE.match(link):
        return link

    qs = parse_qs(urlparse(link).query)
    # Brave typically stores the final dest in "url"
    if "url" in qs and qs["url"]:
        return unquote(qs["url"][0])
    return link