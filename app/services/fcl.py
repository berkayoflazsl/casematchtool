from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlparse

import feedparser
import httpx

from app.config import get_settings

# Extract document path like ewca/civ/2023/454
_URI_RE = re.compile(
    r"caselaw\.nationalarchives\.gov\.uk/([^?#]+?)(?:/data\.xml)?/?$", re.I
)
_REL_PATH_RE = re.compile(
    r"^/?(?:.*/)?(ew[hc]|ewca|ewcop|ewhc|uksc|ukpc|eats|ewfc|eaca)/[^?]+",
    re.I,
)


def public_and_data_url_from_link(href: str) -> tuple[str, str, str] | None:
    """Return (source_uri, public_url, data_url) or None."""
    p = unquote(href)
    m = _URI_RE.search(p)
    if m:
        doc_uri = m.group(1).rstrip("/")
    else:
        m2 = _REL_PATH_RE.search(urlparse(p).path)
        if not m2:
            return None
        # path might be /ewca/civ/2023/454/...
        path = urlparse(p).path.strip("/")
        if "/data.xml" in path:
            path = path.replace("/data.xml", "")
        doc_uri = path
    if "data.xml" in doc_uri:
        return None
    public_url = f"https://caselaw.nationalarchives.gov.uk/{doc_uri}"
    data_url = f"https://caselaw.nationalarchives.gov.uk/{doc_uri}/data.xml"
    return doc_uri, public_url, data_url


def parse_atom_document_uris(content: str) -> list[tuple[str, str, str, str | None]]:
    """
    Return list of (source_uri, public_url, data_url, entry_title) from atom XML string.
    """
    d = feedparser.parse(content)
    out: list[tuple[str, str, str, str | None]] = []
    for e in d.entries:
        title = getattr(e, "title", None)
        href: str | None = None
        for l in getattr(e, "links", []):
            if l.get("rel") == "alternate" and l.get("href"):
                href = l["href"]
                break
        if not href and getattr(e, "link", None):
            href = e.link
        if not href:
            continue
        parts = public_and_data_url_from_link(href)
        if not parts:
            continue
        s_uri, pub, d_url = parts
        out.append((s_uri, pub, d_url, title))
    return out


def next_feed_url(d: feedparser.FeedParserDict) -> str | None:
    for l in d.feed.get("links", []):
        if l.get("rel") == "next" and l.get("href"):
            return l["href"]
    return None


def judgment_text_from_xml_bytes(xml_bytes: bytes) -> str:
    root = ET.fromstring(xml_bytes)
    texts: list[str] = []
    for el in root.iter():
        t = (el.text or "") + (el.tail or "")
        t = t.strip()
        if t and len(t) > 1:
            texts.append(t)
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


async def fetch_text(client: httpx.AsyncClient, url: str) -> str:
    r = await client.get(url, follow_redirects=True, timeout=60.0)
    r.raise_for_status()
    return r.text


async def fetch_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url, follow_redirects=True, timeout=60.0)
    r.raise_for_status()
    return r.content


async def stream_feed_entries(
    start_url: str,
    max_pages: int = 3,
) -> AsyncIterator[tuple[str, str, str, str | None]]:
    """
    Atom feed: sayfa sayfa gez, mükerrer linkleri (aynı source_uri) at.
    Tüketici yeteri kadar toplayınca durur; gerekirse max_pages sayfasına kadar ilerler.
    """
    s = get_settings()
    seen: set[str] = set()
    url: str = start_url
    async with httpx.AsyncClient() as client:
        for _ in range(max_pages):
            body = await fetch_text(client, url)
            rows = parse_atom_document_uris(body)
            for row in rows:
                s_uri = row[0]
                if s_uri in seen:
                    continue
                seen.add(s_uri)
                yield row
            d = feedparser.parse(body)
            nxt = next_feed_url(d)
            if not nxt or nxt == url:
                break
            await asyncio.sleep(s.fcl_request_sleep)
            url = nxt


async def iter_feed_entries(
    start_url: str,
    max_pages: int = 3,
) -> list[tuple[str, str, str, str | None]]:
    out: list[tuple[str, str, str, str | None]] = []
    async for row in stream_feed_entries(start_url, max_pages=max_pages):
        out.append(row)
    return out
