import urllib.parse
from .common import make_session

class BaseAgent:
    """字幕提供商 Agent 基类"""

    def __init__(self, base_url, default_url, dl_location, logger, unpacker):
        self.BASE_URL = (base_url or default_url).rstrip("/")
        self.DOWNLOAD_LOCATION = dl_location
        self.logger = logger
        self.unpacker = unpacker
        self.session = make_session()

    def log(self, msg, level=0):
        self.logger.log(self.__class__.__name__, msg, level)

    def get_page(self, url, referer=None):
        if url and not url.startswith('http'):
            url = urllib.parse.urljoin(self.BASE_URL, url)
        try:
            self.log(f"Requesting URL: {url}")
            headers = {'Referer': referer} if referer else {}
            resp = self.session.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                return resp.content
            self.log(f"Failed to get page {url}, status: {resp.status_code}", 2)
            return None
        except Exception as e:
            self.log(f"Exception getting page {url}: {e}", 2)
            return None

    def _build_language_meta(self, tags):
        """根据 tags 构建 Kodi 语言元数据"""
        langs = tags.get('lang', [])
        if 'eng' in langs and 'chs' not in langs and 'cht' not in langs:
            return "English", "en", "0"
        return "Chinese", "zh", "0"

    def _build_result(self, filename, link, tags):
        language_name, lang_flag, rating = self._build_language_meta(tags)
        return {
            "language_name": language_name,
            "filename": filename,
            "link": link,
            "language_flag": lang_flag,
            "rating": rating,
            "tags": tags
        }

    def close(self):
        self.session.close()
