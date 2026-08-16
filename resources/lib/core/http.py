# -*- coding: utf-8 -*-
"""Shared HTTP and logging utilities for external sites."""
import html
import os
import re
import urllib.parse

import requests

UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

BASE_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1'
}


def noop_log(message):
    """Default no-op logger; every core entry point accepts a `log` callable."""


def make_session(retries=3):
    """Session with browser-like headers and retry policy."""
    session = requests.Session()
    session.headers.update({'User-Agent': UA, **BASE_HEADERS})
    if retries:
        adapter = requests.adapters.HTTPAdapter(max_retries=retries)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
    return session


def filename_from_headers(content_disposition, url=None, default=None):
    """Best-effort filename from a Content-Disposition header, falling back to the URL tail."""
    if content_disposition:
        cd = content_disposition.strip()
        # RFC 5987 filename* wins over the legacy filename parameter
        star = re.findall(r"filename\*\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if star:
            raw = star[0].strip().strip('"').strip("'")
            if "''" in raw:
                raw = raw.split("''", 1)[1]
            return html.unescape(urllib.parse.unquote(raw))
        plain = re.findall(r"filename\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if plain:
            return html.unescape(plain[0].strip().strip('"').strip("'"))
    if url:
        tail = os.path.basename(urllib.parse.urlparse(url).path)
        if tail:
            return tail
    return default
