# -*- coding: utf-8 -*-
"""Zimuku (zimuku.org) subtitle provider, including its BMP captcha solver."""
import base64
import html
import re
import struct
import urllib.parse

from bs4 import BeautifulSoup

from .archive import ARCHIVE_EXTS, SUBTITLE_EXTS, save_and_extract
from .http import filename_from_headers, make_session, noop_log
from .matcher import parse_meta
from .models import DownloadResult, Subtitle, Tags, Work

MAX_CAPTCHA_RETRIES = 3
FILE_MIN_SIZE = 1024  # smaller responses are error pages, not subtitles


class ZimukuSolver:
    """Recognizes the 5 digits of Zimuku's 100x27 BMP captcha via template matching."""

    IMG_WIDTH, IMG_HEIGHT = 100, 27
    CHAR_WIDTH, NUM_CHARS = 20, 5
    PIXEL_DATA_OFFSET = 54

    SAMPLE_POINTS = [
        (10, 7), (7, 8), (12, 8), (10, 13),
        (7, 19), (12, 19), (10, 20), (6, 13), (14, 13)
    ]

    TEMPLATES = {
        '0': [1, 1, 1, 1, 1, 1, 1, 1, 0],
        '1': [0, 1, 0, 0, 0, 0, 1, 0, 0],
        '2': [1, 0, 1, 0, 1, 0, 1, 0, 0],
        '3': [1, 0, 1, 1, 0, 1, 1, 0, 0],
        '4': [0, 0, 1, 0, 0, 1, 0, 0, 0],
        '5': [1, 1, 0, 0, 0, 1, 1, 0, 0],
        '6': [1, 0, 1, 1, 1, 1, 1, 1, 0],
        '7': [1, 0, 1, 0, 0, 0, 0, 0, 0],
        '8': [1, 1, 1, 1, 1, 1, 1, 0, 0],
        '9': [1, 1, 1, 0, 1, 0, 1, 0, 0],
    }

    def __init__(self, b64_string):
        try:
            self._data = base64.b64decode(b64_string)
        except (ValueError, TypeError):
            raise ValueError("Invalid Base64 string")
        if len(self._data) < self.PIXEL_DATA_OFFSET or self._data[:2] != b'BM':
            raise ValueError("Invalid BMP data")
        w = struct.unpack_from('<i', self._data, 18)[0]
        h = struct.unpack_from('<i', self._data, 22)[0]
        if (w, h) != (self.IMG_WIDTH, self.IMG_HEIGHT):
            raise ValueError(f"Expected {self.IMG_WIDTH}x{self.IMG_HEIGHT}, got {w}x{h}")
        self._stride = (self.IMG_WIDTH * 3 + 3) & ~3

    def recognize(self):
        result = []
        one_offset = 0  # narrow glyphs ('1'/'4') shift following sample points
        for i in range(self.NUM_CHARS):
            char_x = i * self.CHAR_WIDTH
            features = [
                1 if self._is_foreground(char_x + px - one_offset, py) else 0
                for px, py in self.SAMPLE_POINTS
            ]
            digit = self._match_digit(features)
            if digit == '1':
                one_offset += 1
            elif digit == '4':
                one_offset -= 1
            result.append(digit)
        return "".join(result)

    def _is_foreground(self, x, y, threshold=70):
        bmp_y = self.IMG_HEIGHT - 1 - y  # BMP rows are bottom-up
        offset = self.PIXEL_DATA_OFFSET + bmp_y * self._stride + x * 3
        b, g, r = self._data[offset], self._data[offset + 1], self._data[offset + 2]
        return (r + g + b) / 3 < threshold

    def _match_digit(self, features):
        best, min_diff = '?', float('inf')
        for digit, template in self.TEMPLATES.items():
            diff = sum(f != t for f, t in zip(features, template))
            if diff < min_diff:
                min_diff, best = diff, digit
            if min_diff == 0:
                break
        return best


class ZimukuProvider:
    name = "zimuku"
    BASE_URL = "https://zimuku.org"

    def __init__(self, log=noop_log, backend=None):
        self.log = log
        self.backend = backend
        self.session = make_session()

    def _get(self, url, referer=None):
        """GET with the site's Yunsuo WAF captcha loop (may need several passes)."""
        if url and not url.startswith("http"):
            url = urllib.parse.urljoin(self.BASE_URL, url)
        headers = {"Referer": referer} if referer else {}
        resp = None
        for attempt in range(MAX_CAPTCHA_RETRIES + 1):
            try:
                resp = self.session.get(url, headers=headers, timeout=10)
            except Exception as e:
                self.log(f"zimuku: GET {url} failed: {e}")
                return None
            if resp.status_code == 200 and b'class="verifyimg"' not in resp.content:
                return resp.content
            if resp.content and b'class="verifyimg"' in resp.content:
                if attempt < MAX_CAPTCHA_RETRIES:
                    self._solve_captcha(url, resp.content, headers)
                    continue
                self.log(f"zimuku: captcha failed after {MAX_CAPTCHA_RETRIES} attempts")
                return None
            break
        self.log(f"zimuku: GET {url} -> HTTP {resp.status_code if resp else 'N/A'}")
        return None

    def _solve_captcha(self, url, page_content, headers=None):
        """Answer the inline BMP captcha by replaying the security_verify_img call."""
        try:
            img = BeautifulSoup(page_content, "html.parser").find(attrs={"class": "verifyimg"})
            if not img:
                return
            src = img.get("src", "")
            if "data:image/bmp;base64," not in src:
                return
            text = ZimukuSolver(src.split("data:image/bmp;base64,", 1)[1]).recognize()
            hex_str = "".join(f"{ord(c):x}" for c in text)
            sep = "&" if "?" in url else "?"
            self.session.get(f"{url}{sep}security_verify_img={hex_str}", headers=headers)
        except Exception as e:
            self.log(f"zimuku: captcha error: {e}")

    # ---- works ----

    MAX_SEARCH_PAGES = 10

    def find_works(self, query):
        """Search the site for works: /search?q=... first, &p=2... after,
        capped at MAX_SEARCH_PAGES. Stops only on a failed or empty result
        page — a page of already-seen entries does not end it early.

        Measured: like SubHD, multi-word queries are token-AND matched with
        stopwords ignored, and %20 vs + space encoding are equivalent —
        send titles verbatim."""
        if not query.title:
            return []
        base = f"{self.BASE_URL}/search?q={urllib.parse.quote(query.title)}&chost=zimuku.org"
        works, seen = [], set()
        for page in range(1, self.MAX_SEARCH_PAGES + 1):
            url = base if page == 1 else f"{base}&p={page}"
            data = self._get(url)
            if not data:
                break
            items = BeautifulSoup(data, "html.parser").select("div.item")
            if not items:
                break
            for item in items:
                link = item.select_one("div.title p.tt a")
                if not link:
                    continue
                href = link.get("href", "")
                if not re.search(r"/subs/\d+\.html", href):
                    continue
                subs_url = urllib.parse.urljoin(self.BASE_URL, href)
                if subs_url in seen:
                    continue
                seen.add(subs_url)
                title = link.get_text(strip=True)
                if not title:
                    continue
                _, season, year = parse_meta(title)
                works.append(Work(title=title, season=season, year=year,
                                  anchors={"zimuku": [subs_url]}))
        return works

    # ---- search ----

    def search(self, query, work):
        """List subtitles for every /subs/{id}.html page the work anchors."""
        results = []
        production = "剧集" if query.is_tv else "电影"
        matches_episode = self._episode_filter(query.season, query.episode)
        for subs_url in (work.anchors.get("zimuku") or []) if work else []:
            data = self._get(subs_url)
            if not data:
                continue
            box = BeautifulSoup(data, "html.parser").select_one("div.subs.box.clearfix")
            if not box or not box.tbody:
                continue
            for row in reversed(box.tbody.find_all("tr")):
                include, collection = matches_episode(row.a.text)
                if include:
                    results.append(self._parse_row(row, production, collection))
        return results

    def _parse_row(self, row, production, collection):
        link = urllib.parse.urljoin(self.BASE_URL, row.a["href"])
        langs = []
        td = row.find("td", class_="tac lang")
        if td:
            langs = [img.get("title", "").rstrip("字幕") for img in td.find_all("img")]
        tags = Tags(production=production, collection=collection)
        fmt_span = row.find("span", class_="label-info")
        if fmt_span:
            tags.fmt = [f.strip() for f in fmt_span.text.strip().lower().split("/")]
        fansub_link = row.select_one('a[href^="/t/"]')
        if fansub_link:
            tags.fansub = fansub_link.text.strip()
        else:
            danger = row.find("span", class_="label-danger")
            if danger:
                tags.fansub = danger.text.strip()
        if "简体中文" in langs: tags.lang.append("chs")
        if "繁體中文" in langs: tags.lang.append("cht")
        if "English" in langs: tags.lang.append("eng")
        if "双语" in langs: tags.bilingual = True
        return Subtitle(row.a.text, link, tags)

    @staticmethod
    def _episode_filter(season, episode):
        """Return fn(name) -> (include, collection) matching the wanted episode."""
        if not (season and episode and str(season).isdigit() and str(episode).isdigit()):
            return lambda name: (True, False)
        ep = int(episode)
        tokens = [f"S{int(season):02d}E{ep:02d}", f"E{ep:02d}", f"EP{ep:02d}",
                  f"E{ep}", f"EP{ep}", f"第{ep}集"]
        tag_re = re.compile(r'(S\d{1,2}\s*(E|EP)\d{1,3})|(\bEP?\d{1,3}\b)|(第\s*\d+\s*集)')
        ep_re = re.compile(rf'(?<!\d)({"|".join(re.escape(t) for t in tokens)})(?!\d)', re.IGNORECASE)

        def matches(name):
            upper = name.upper()
            has_tag = tag_re.search(upper) is not None
            return (not has_tag or bool(ep_re.search(upper)), not has_tag)
        return matches

    # ---- download ----

    def download(self, link, dest):
        """Follow detail -> dl page -> file links; first believable file wins."""
        try:
            data = self._get(link)
            if not data:
                return DownloadResult()
            soup = BeautifulSoup(data, "html.parser")
            dl_link = soup.find("li", class_="dlsub")
            if not dl_link or not dl_link.a:
                return DownloadResult()
            dl_url = urllib.parse.urljoin(self.BASE_URL, dl_link.a["href"])
            data = self._get(dl_url)
            if not data:
                return DownloadResult()
            links = BeautifulSoup(data, "html.parser").find("div", class_="clearfix")
            if not links:
                return DownloadResult()
            links = links.find_all("a")
        except Exception as e:
            self.log(f"zimuku: download page parse failed: {e}")
            return DownloadResult()

        filename = file_data = None
        for a in links:
            href = a.get("href")
            if not href:
                continue
            file_url = urllib.parse.urljoin(self.BASE_URL, href)
            try:
                resp = self.session.get(file_url, headers={"Referer": dl_url}, timeout=10)
                if resp.status_code != 200:
                    continue
                filename = filename_from_headers(resp.headers.get("Content-Disposition"), url=file_url)
                if not filename:
                    continue
                file_data = resp.content
                if len(file_data) > FILE_MIN_SIZE:
                    break
            except Exception as e:
                self.log(f"zimuku: download {file_url} failed: {e}")
        if not filename or not file_data or len(file_data) <= FILE_MIN_SIZE:
            return DownloadResult()

        filename = html.unescape(filename)
        dot = filename.rfind(".")
        if dot != -1:
            filename = filename[:dot] + filename[dot:].lower()
        if filename.lower().endswith(SUBTITLE_EXTS) or filename.lower().endswith(ARCHIVE_EXTS):
            return save_and_extract(dest, filename, file_data, self.backend)
        return DownloadResult()
