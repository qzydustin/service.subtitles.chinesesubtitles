# -*- coding: utf-8 -*-
"""SubHD (subhd.tv) subtitle provider, including its SVG captcha solver."""
import re
import urllib.parse

from bs4 import BeautifulSoup

from .archive import save_and_extract
from .http import filename_from_headers, make_session, noop_log
from .matcher import parse_meta
from .models import DownloadResult, Subtitle, Tags, Work

FORMATS = ("ASS", "SRT", "SSA", "SUB", "SUP", "VTT")
# Chinese origin badge -> normalized source tag
SOURCE_MAP = {"转载精修": "reprint", "官方字幕": "official", "原创翻译": "original",
              "机器翻译": "machine", "AI翻润色": "ai"}


class SubhdSolver:
    """Solver for SubHD's SVG captchas, keyed on path length (from index.js)."""

    LENGTH_MAP = {
        986: ['I', 'l'], 998: ['1'], 1068: ['I', 'l'], 1081: ['1'], 1082: ['v'],
        1130: ['Y'], 1134: ['Y'], 1172: ['v'], 1224: ['Y'], 1274: ['L', 'y'],
        1298: ['V'], 1311: ['V'], 1360: ['i'], 1380: ['L', 'y'], 1406: ['V'],
        1473: ['i'], 1478: ['T'], 1491: ['r'], 1598: ['N', 'X'], 1601: ['T'],
        1604: ['X'], 1610: ['J', 'x'], 1613: ['x'], 1614: ['N'], 1615: ['r', 'N'],
        1616: ['N'], 1617: ['N'], 1618: ['N'], 1634: ['k'], 1637: ['k'],
        1694: ['z', 't'], 1706: ['K'], 1709: ['K'], 1731: ['X', 'N'], 1744: ['x', 'J'],
        1754: ['F'], 1770: ['k'], 1835: ['z', 't'], 1838: ['u'], 1840: ['A'],
        1844: ['A'], 1848: ['K'], 1850: ['Z'], 1853: ['Z'], 1886: ['h'],
        1900: ['F'], 1922: ['H'], 1928: ['H'], 1960: ['P'], 1991: ['u'],
        1993: ['A'], 1996: ['D'], 2004: ['Z'], 2018: ['w'], 2035: ['w'],
        2042: ['7'], 2043: ['h'], 2080: ['j'], 2082: ['H'], 2104: ['R'],
        2107: ['R'], 2123: ['P'], 2140: ['4'], 2162: ['D'], 2164: ['O'],
        2183: ['w'], 2198: ['n', 'C'], 2199: ['C'], 2200: ['C'], 2201: ['C'],
        2202: ['C'], 2210: ['f'], 2212: ['7'], 2246: ['E'], 2253: ['j'],
        2260: ['o'], 2272: ['d'], 2279: ['R', 'M'], 2282: ['M'], 2294: ['U'],
        2301: ['U'], 2310: ['W'], 2318: ['4', 'W'], 2321: ['M'], 2332: ['a'],
        2344: ['O'], 2345: ['W'], 2346: ['W'], 2366: ['s'], 2380: ['b'],
        2381: ['n', 'C'], 2382: ['0'], 2394: ['f'], 2433: ['E'], 2448: ['o'],
        2461: ['d'], 2464: ['p'], 2466: ['M'], 2485: ['U'], 2498: ['c'],
        2501: ['e'], 2503: ['W'], 2512: ['q'], 2526: ['a'], 2546: ['2'],
        2563: ['s'], 2578: ['b'], 2580: ['0'], 2606: ['5'], 2632: ['6'],
        2669: ['p'], 2706: ['c'], 2709: ['e'], 2721: ['q'], 2758: ['2'],
        2800: ['9'], 2823: ['5'], 2851: ['6'], 3033: ['9'], 3038: ['S'],
        3054: ['B'], 3160: ['g'], 3244: ['Q'], 3254: ['Q'], 3266: ['G'],
        3291: ['S'], 3308: ['B'], 3414: ['8'], 3423: ['g'], 3514: ['Q'],
        3538: ['G'], 3663: ['m'], 3667: ['m'], 3698: ['8'], 3878: ['3'],
        3968: ['m'], 4201: ['3']
    }

    def solve(self, svg_content):
        """Read the captcha text from path d-attributes (>500 chars = glyphs)."""
        candidates = []
        for match in re.finditer(r'd="([^"]+)"', svg_content):
            d = match.group(1)
            if len(d) > 500:
                x_match = re.search(r'(\d+(?:\.\d*)?)', d)
                candidates.append((float(x_match.group(1)) if x_match else 0.0, d))
        candidates.sort(key=lambda c: c[0])

        result = []
        for _, d in candidates:
            char = self._resolve_collision(len(d), d)
            if not char:
                char = self.LENGTH_MAP.get(len(d), [''])[0]
            result.append(char)
        return "".join(result)

    def _resolve_collision(self, length, d):
        """Disambiguate glyphs sharing a path length using geometry."""
        numbers = [float(m) for m in re.findall(r'(\d+(?:\.\d*)?)', d)]
        xs, ys = numbers[0::2], numbers[1::2]
        min_y = min(ys) if ys else 0.0
        width = (max(xs) - min(xs)) if xs else 0.0
        move = re.search(r'M(\d+(?:\.\d*)?)\s+(\d+(?:\.\d*)?)', d)
        move_y = float(move.group(2)) if move else 0.0

        if length in (986, 1068): return 'I' if min_y > 13 else 'l'
        if length in (1274, 1380): return 'y' if move_y > 30 else 'L'
        if length in (1610, 1744): return 'x' if min_y > 19 else 'J'
        if length == 1615: return 'r' if min_y > 18 else 'N'
        if length in (2198, 2381): return 'n' if min_y > 19 else 'C'
        if length == 2318: return 'W' if width > 30 else '4'
        if length in (1598, 1731): return 'X' if min_y > 13 else 'N'
        if length in (1694, 1835): return 'z' if min_y > 22 else 't'
        if length == 2279: return 'R' if min_y > 13 else 'M'
        return None


class SubhdProvider:
    name = "subhd"
    BASE_URL = "https://subhd.tv"

    def __init__(self, log=noop_log, backend=None):
        self.log = log
        self.backend = backend  # archive backend for rar/7z (Kodi vfs)
        self.session = make_session()

    def _get(self, url, referer=None):
        try:
            resp = self.session.get(url, headers={"Referer": referer} if referer else {}, timeout=10)
            if resp.status_code == 200:
                return resp.content
            self.log(f"subhd: GET {url} -> HTTP {resp.status_code}")
        except Exception as e:
            self.log(f"subhd: GET {url} failed: {e}")
        return None

    # ---- works ----

    MAX_SEARCH_PAGES = 10

    def find_works(self, query):
        """Search the site for works matching the query title.

        The first page is /search/{q} (the /1 suffix returns the same page);
        following pages are /search/{q}/2 and up, capped at MAX_SEARCH_PAGES.
        Result anchors are poster links whose text is empty; the title lives
        in the poster img.alt. Parsing must be scoped to div.col-lg-9:
        div.col-lg-3 is an unrelated "IMDb hot" sidebar ranking.

        Measured: multi-word queries are token-AND matched and stopwords are
        ignored ("The Lord of the Rings" ≡ "Lord of the Rings") — send titles
        verbatim, no truncation or stopword stripping.

        Pagination stops only on a failed/unparseable/empty result page —
        a page of already-seen entries does not end it early.
        """
        if not query.title:
            return []
        q = urllib.parse.quote(query.title)
        works, seen = [], set()
        for page in range(self.MAX_SEARCH_PAGES):
            url = (f"{self.BASE_URL}/search/{q}" if page == 0
                   else f"{self.BASE_URL}/search/{q}/{page + 1}")
            content = self._get(url)
            if not content:
                break
            container = BeautifulSoup(content, "html.parser").select_one("div.col-lg-9")
            if not container:
                break
            links = container.select('a[href^="/d/"]')
            if not links:
                break
            for link in links:
                href = link["href"]
                if href in seen:
                    continue
                seen.add(href)
                img = link.find("img")
                title = (img.get("alt") or "").strip() if img else ""
                if not title:
                    self.log(f"subhd: poster without alt at {href}, skipped")
                    continue
                _, season, year = parse_meta(title)
                works.append(Work(title=title, season=season, year=year,
                                  anchors={"subhd": [href]}))
        return works

    # ---- search ----

    def search(self, query, work):
        """List subtitles for every /d/{id} page the work anchors."""
        results = []
        episode = query.episode if query.is_tv else None
        for href in (work.anchors.get("subhd") or []) if work else []:
            content = self._get(urllib.parse.urljoin(self.BASE_URL, href))
            if not content:
                continue
            results += self._parse_list(content, episode)
        production = "剧集" if query.is_tv else "电影"
        for r in results:
            r.tags.production = production
        return results

    def _parse_list(self, content, target_episode=None):
        """Parse the work page; bg-light headers split movie/collection/episode rows."""
        soup = BeautifulSoup(content, "html.parser")
        container = soup.select_one("div.bg-white.shadow-sm.rounded-3.mb-5")
        if not container:
            return []
        results, category = [], "general"
        for child in container.children:
            if child.name != "div":
                continue
            classes = child.get("class", [])
            if "bg-light" in classes:
                text = child.get_text().strip()
                if "合集" in text:
                    category = "collection"
                elif "第" in text and "集" in text:
                    match = re.search(r"第\s*(\d+)\s*集", text)
                    category = int(match.group(1)) if match else "general"
                else:
                    category = "general"
            elif "row" in classes:
                if target_episode:
                    target = int(target_episode) if str(target_episode).isdigit() else target_episode
                    if category == target or str(category) == str(target_episode):
                        is_collection = False
                    elif category == "collection":
                        is_collection = True
                    else:
                        continue
                else:
                    is_collection = category == "collection"
                link = child.select_one("a.link-dark")
                if not link or not link.get("href", "").startswith("/a/"):
                    continue
                tags = self._parse_tags(child.find_all("span"))
                tags.collection = is_collection
                fansub = child.select_one('a[href^="/zu/"]') or child.select_one('a[href^="/u/"]')
                tags.fansub = fansub.get_text().strip() if fansub else ""
                results.append(Subtitle(link.get_text().strip(), self.BASE_URL + link["href"], tags))
        return results

    def _parse_tags(self, spans):
        tags = Tags()
        for span in spans:
            classes = span.get("class", [])
            text = span.get_text().strip()
            if "rounded" in classes and "text-white" in classes:
                for cn, key in SOURCE_MAP.items():
                    if cn in text:
                        tags.source.append(key)
                        break
            if "fw-bold" in classes:
                if "简体" in text: tags.lang.append("chs")
                if "繁体" in text: tags.lang.append("cht")
                if "英语" in text: tags.lang.append("eng")
                if "双语" in text: tags.bilingual = True
            if "text-secondary" in classes:
                for fmt in FORMATS:
                    if fmt in text.upper():
                        tags.fmt.append(fmt.lower())
                        break
        return tags

    # ---- download ----

    def _resolve_down_url(self, page_url, soup):
        """Resolve the one-time temp download page.

        Since the 2026-08 redesign the detail page has no /down/ link; a
        button (button.down[data-sid]) must be exchanged via
        POST /api/sub/prepare-download (direct /down/{sid} returns 403).
        The legacy <a class="down"> link is kept as fallback.
        """
        sid = None
        button = soup.find("button", class_="down")
        if button:
            sid = button.get("data-sid") or button.get("sid")
        if not sid:
            match = re.search(r"/a/([^/?#]+)", page_url)
            sid = match.group(1) if match else None
        if sid:
            try:
                resp = self.session.post(
                    self.BASE_URL + "/api/sub/prepare-download",
                    json={"sid": sid},
                    headers={"Referer": page_url, "X-Requested-With": "XMLHttpRequest"},
                    timeout=10)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("success") and data.get("url"):
                        url = data["url"]
                        return url if url.startswith("http") else self.BASE_URL + url
                    self.log(f"subhd: prepare-download failed: {data.get('msg')}")
                else:
                    self.log(f"subhd: prepare-download HTTP {resp.status_code}")
            except Exception as e:
                self.log(f"subhd: prepare-download failed: {e}")
        for a in soup.find_all("a", class_="down"):
            href = a.get("href", "")
            if "/down/" in href:
                return href if href.startswith("http") else self.BASE_URL + href
        return None

    def download(self, link, dest):
        """Fetch, extract and store one subtitle into dest."""
        content = self._get(link)
        if not content:
            return DownloadResult()
        soup = BeautifulSoup(content, "html.parser")
        down_url = self._resolve_down_url(link, soup)
        if not down_url:
            self.log("subhd: no download entry found on page")
            return DownloadResult()
        if not self._get(down_url, referer=link):
            return DownloadResult()
        sid = down_url.split("/")[-1].split("?")[0].split("#")[0]
        api_url = self.BASE_URL + "/api/sub/down"
        try:
            payload = {"sid": sid, "cap": ""}
            resp = self.session.post(api_url, json=payload, headers={"Referer": down_url}, timeout=10)
            if resp.status_code != 200:
                return DownloadResult()
            data = resp.json()
            if data.get("pass") == False:
                svg = data.get("msg")
                if svg:
                    # Returned under IP throttling; hard to reproduce with a clean IP.
                    # Keep the same solve-and-retry logic as the old flow.
                    payload["cap"] = SubhdSolver().solve(svg)
                    resp = self.session.post(api_url, json=payload, headers={"Referer": down_url}, timeout=10)
                    data = resp.json()
            if not data.get("success"):
                return DownloadResult()
            file_url = data.get("url")
            if not file_url:
                return DownloadResult()
            if not file_url.startswith("http"):
                file_url = self.BASE_URL + file_url
            file_resp = self.session.get(file_url, headers={"Referer": down_url}, timeout=15)
            filename = filename_from_headers(
                file_resp.headers.get("Content-Disposition"),
                url=file_resp.url or file_url, default="subtitle.bin")
            return save_and_extract(dest, filename, file_resp.content, self.backend)
        except Exception as e:
            self.log(f"subhd: download failed: {e}")
            return DownloadResult()
