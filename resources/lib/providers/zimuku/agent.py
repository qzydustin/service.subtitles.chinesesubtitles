import re
import urllib.parse
from bs4 import BeautifulSoup
from .captcha import ZimukuSolver
from ..base import BaseAgent
from ..common import get_filename_from_cd, save_and_unpack, SUBTITLE_EXTS, ARCHIVE_EXTS

class ZimukuAgent(BaseAgent):

    def __init__(self, base_url, dl_location, logger, unpacker):
        super().__init__(base_url, "https://zimuku.org", dl_location, logger, unpacker)
        import requests
        self.session.mount('https://', requests.adapters.HTTPAdapter(max_retries=3))

    MAX_CAPTCHA_RETRIES = 3

    def get_page(self, url, referer=None):
        """重写以支持验证码处理，Zimuku需要连续解决多次验证码"""
        if url and not url.startswith('http'):
            url = urllib.parse.urljoin(self.BASE_URL, url)
        headers = {'Referer': referer} if referer else {}
        try:
            for attempt in range(self.MAX_CAPTCHA_RETRIES + 1):
                resp = self.session.get(url, headers=headers, timeout=10)
                if resp is None:
                    break
                # 成功：200 且无验证码
                if resp.status_code == 200 and b'class="verifyimg"' not in resp.content:
                    return resp.content
                # 包含验证码 - 需要解决（可能需要连续多次）
                if resp.content and b'class="verifyimg"' in resp.content:
                    if attempt < self.MAX_CAPTCHA_RETRIES:
                        self._solve_captcha(url, resp.content, headers)
                        # 不 break，继续循环再次请求（可能仍需解决验证码）
                        continue
                    else:
                        self.log(f"Captcha failed after {self.MAX_CAPTCHA_RETRIES} attempts", 2)
                        return None
                # 非 200 且无验证码 - 真正的错误
                if resp.status_code != 200:
                    break
            status = resp.status_code if resp is not None else 'N/A'
            self.log(f"Failed to get page {url}, status: {status}", 2)
            return None
        except Exception as e:
            self.log(f"Exception getting page {url}: {e}", 2)
            return None

    def _solve_captcha(self, url, page_content, headers=None):
        """处理 Zimuku 验证码"""
        try:
            soup = BeautifulSoup(page_content, 'html.parser')
            img = soup.find(attrs={'class': 'verifyimg'})
            if not img: return
            img_src = img.get('src', '')
            if 'data:image/bmp;base64,' not in img_src: return
            b64 = img_src.split('data:image/bmp;base64,', 1)[1]
            text = ZimukuSolver(b64).recognize()
            hex_str = ''.join(f'{ord(c):x}' for c in text)
            sep = '&' if '?' in url else '?'
            verify_url = f"{url}{sep}security_verify_img={hex_str}"
            self.session.get(verify_url, headers=headers)
        except Exception as e:
            self.log(f"Captcha error: {e}", 2)

    def search_candidates(self, title, year=None, is_tv=False):
        """搜索候选作品列表"""
        if not title: return []
        query = title
        search_url = f"{self.BASE_URL}/search?q={urllib.parse.quote(query)}&chost=zimuku.org"
        data = self.get_page(search_url)
        if not data: return []
        soup = BeautifulSoup(data, "html.parser")
        results, seen = [], set()
        for item in soup.select('div.item'):
            link = item.select_one('div.title p.tt a')
            if not link: continue
            href = link.get("href", "")
            if not re.search(r"/subs/\d+\.html", href): continue
            subs_url = urllib.parse.urljoin(self.BASE_URL, href)
            if subs_url in seen: continue
            seen.add(subs_url)
            label = link.get_text(strip=True)
            if label:
                results.append({"label": f"[备用] {label}", "title": label, "type": "tv" if is_tv else "movie", "source": "zimuku", "zimuku_subs_url": subs_url})
        return results

    def get_douban_id_from_subs(self, subs_url):
        """从字幕页面提取豆瓣 ID"""
        if not subs_url: return None
        data = self.get_page(subs_url)
        if not data: return None
        soup = BeautifulSoup(data, "html.parser")
        link = soup.find("a", href=re.compile(r"movie\.douban\.com/subject/\d+/"))
        if not link:
            img = soup.find("img", src=re.compile(r"douban_(big|icon)\.png"))
            if img and img.parent.name == "a": link = img.parent
        if link:
            match = re.search(r"subject/(\d+)/", link.get("href", ""))
            return match.group(1) if match else None
        return None

    def _extract_sub_info(self, sub, production=None, collection=False):
        """解析单个字幕条目"""
        link = urllib.parse.urljoin(self.BASE_URL, sub.a.get('href'))
        name = sub.a.text
        langs = []
        try:
            td = sub.find("td", class_="tac lang")
            if td: langs = [img.get('title', '').rstrip('字幕') for img in td.find_all("img")]
        except Exception: pass
        rating = "0"
        try:
            star = sub.find("i", class_="rating-star")
            if star:
                star_str = str(star)
                idx = star_str.find("allstar")
                if idx >= 0 and idx + 7 < len(star_str) and star_str[idx + 7].isdigit(): rating = star_str[idx + 7]
        except Exception: pass
        tags = {"source": [], "lang": [], "fmt": [], "bilingual": False, "production": production or "", "collection": bool(collection)}
        fmt_span = sub.find("span", class_="label-info")
        if fmt_span:
            fmt_text = fmt_span.text.strip().lower()
            tags["fmt"] = [f.strip() for f in fmt_text.split('/')] if '/' in fmt_text else [fmt_text]
        fansub_link = sub.select_one('a[href^="/t/"]')
        if fansub_link: tags["fansub"] = fansub_link.text.strip()
        else:
            danger = sub.find("span", class_="label-danger")
            if danger: tags["fansub"] = danger.text.strip()
        if '简体中文' in langs: tags["lang"].append("chs")
        if '繁體中文' in langs: tags["lang"].append("cht")
        if 'English' in langs: tags["lang"].append("eng")
        if '双语' in langs: tags["bilingual"] = True
        return self._build_result(name, link, tags)

    def _build_episode_filter(self, season, episode):
        """构建剧集过滤器"""
        if not (season and episode and str(season).isdigit() and str(episode).isdigit()): return lambda name: (True, False)
        ep = int(episode)
        tokens = [f"S{int(season):02d}E{ep:02d}", f"E{ep:02d}", f"EP{ep:02d}", f"E{ep}", f"EP{ep}", f"第{ep}集"]
        tag_re = re.compile(r'(S\d{1,2}\s*(E|EP)\d{1,3})|(\bEP?\d{1,3}\b)|(第\s*\d+\s*集)')
        ep_re = re.compile(rf'(?<!\d)({"|".join(re.escape(t) for t in tokens)})(?!\d)', re.IGNORECASE)
        def fn(name):
            upper = name.upper()
            has_tag = tag_re.search(upper) is not None
            matches = ep_re.search(upper) is not None
            return (not has_tag or matches, not has_tag)
        return fn

    def search(self, items, candidate=None):
        """搜索字幕"""
        if not candidate: return []
        subs_url = candidate.get('zimuku_subs_url')
        production = "剧集" if candidate.get('type') == 'tv' or items.get('tvshow') else "电影"
        if not subs_url:
            douban_id = candidate.get('id')
            if not douban_id: return []
            search_url = f"{self.BASE_URL}/search?q={urllib.parse.quote(str(douban_id))}&chost=zimuku.org"
            data = self.get_page(search_url)
            if not data: return []
            soup = BeautifulSoup(data, 'html.parser')
            link = soup.find('a', href=re.compile(r'/subs/\d+\.html'))
            if not link: return []
            subs_url = urllib.parse.urljoin(self.BASE_URL, link.get('href'))
        data = self.get_page(subs_url)
        if not data: return []
        box = BeautifulSoup(data, 'html.parser').select_one("div.subs.box.clearfix")
        if not box or not box.tbody: return []
        subs = box.tbody.find_all("tr")
        ep_filter = self._build_episode_filter(items.get('season'), items.get('episode'))
        results = []
        for sub in reversed(subs):
            include, is_coll = ep_filter(sub.a.text)
            if include: results.append(self._extract_sub_info(sub, production, is_coll))
        return results

    def download(self, url):
        """下载字幕"""
        try:
            data = self.get_page(url)
            if not data: return [], [], []
            soup = BeautifulSoup(data, 'html.parser')
            dl_link = soup.find("li", class_="dlsub")
            if not dl_link or not dl_link.a: return [], [], []
            dl_url = urllib.parse.urljoin(self.BASE_URL, dl_link.a.get('href'))
            data = self.get_page(dl_url)
            if not data: return [], [], []
            soup = BeautifulSoup(data, 'html.parser')
            links = soup.find("div", class_="clearfix")
            if not links: return [], [], []
            links = links.find_all('a')
            referer = dl_url
        except Exception: return [], [], []
        filename, file_data = None, None
        for link in links:
            href = link.get('href')
            if not href: continue
            file_url = urllib.parse.urljoin(self.BASE_URL, href)
            try:
                resp = self.session.get(file_url, headers={'Referer': referer}, timeout=10)
                if resp is None or resp.status_code != 200: continue
                filename = get_filename_from_cd(resp.headers.get('Content-Disposition'), url=file_url)
                if not filename: continue
                file_data = resp.content
                if file_data: break
            except Exception: pass
        if not filename or not file_data:
            return [], [], []
        dot = filename.rfind(".")
        if dot != -1: filename = filename[:dot] + filename[dot:].lower()
        if filename.endswith(SUBTITLE_EXTS) or filename.endswith(ARCHIVE_EXTS):
            return save_and_unpack(self.DOWNLOAD_LOCATION, self.unpacker, filename, file_data)
        return [], [], []
