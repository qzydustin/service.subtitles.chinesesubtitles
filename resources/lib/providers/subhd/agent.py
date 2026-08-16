import re
from bs4 import BeautifulSoup
from ..base import BaseAgent
from ..common import get_filename_from_cd, save_and_unpack

FORMATS = ["ASS", "SRT", "SSA", "SUB", "SUP", "VTT"]

class SubHDAgent(BaseAgent):
    def __init__(self, base_url, dl_location, logger, unpacker):
        super().__init__(base_url, "https://subhd.tv", dl_location, logger, unpacker)

    def _extract_tags(self, spans):
        """从 spans 提取标签信息"""
        tags = {'source': [], 'lang': [], 'fmt': [], 'bilingual': False}
        for span in spans:
            classes = span.get('class', [])
            text = span.get_text().strip()
            if 'rounded' in classes and 'text-white' in classes:
                src_map = {'转载精修': 'reprint', '官方字幕': 'official', '原创翻译': 'original', '机器翻译': 'machine', 'AI翻润色': 'ai'}
                for k, v in src_map.items():
                    if k in text:
                        tags['source'].append(v)
                        break
            if 'fw-bold' in classes:
                if '简体' in text: tags['lang'].append('chs')
                if '繁体' in text: tags['lang'].append('cht')
                if '英语' in text: tags['lang'].append('eng')
                if '双语' in text: tags['bilingual'] = True
            if 'text-secondary' in classes:
                for fmt in FORMATS:
                    if fmt in text.upper():
                        tags['fmt'].append(fmt.lower())
                        break
        return tags

    def _parse_subtitles(self, content, target_episode=None):
        """解析字幕列表页面"""
        soup = BeautifulSoup(content, 'html.parser')
        container = soup.select_one('div.bg-white.shadow-sm.rounded-3.mb-5')
        if not container: return []
        results = []
        category = "general"
        for child in container.children:
            if child.name != 'div': continue
            classes = child.get('class', [])
            if 'bg-light' in classes:
                text = child.get_text().strip()
                if "合集" in text:
                    category = "collection"
                elif "第" in text and "集" in text:
                    match = re.search(r'第\s*(\d+)\s*集', text)
                    category = int(match.group(1)) if match else "general"
                else:
                    category = "general"
            elif 'row' in classes:
                is_match, is_coll = False, False
                if target_episode:
                    t_ep = int(target_episode) if str(target_episode).isdigit() else target_episode
                    if category == t_ep or str(category) == str(target_episode): is_match = True
                    elif category == "collection": is_match, is_coll = True, True
                else:
                    is_match = True
                    is_coll = category == "collection"
                if not is_match: continue
                link = child.select_one('a.link-dark')
                if not link: continue
                href = link.get('href', '')
                if not href.startswith('/a/'): continue
                tags = self._extract_tags(child.find_all('span'))
                if is_coll: tags['collection'] = True
                zu = child.select_one('a[href^="/zu/"]') or child.select_one('a[href^="/u/"]')
                tags['fansub'] = zu.get_text().strip() if zu else ""
                results.append(self._build_result(link.get_text().strip(), self.BASE_URL + href, tags))
        return results

    def _resolve_imdb(self, imdb_id):
        """Search SubHD by IMDB ID and return the internal subtitle page ID."""
        search_url = f"{self.BASE_URL}/search/{imdb_id}"
        content = self.get_page(search_url)
        if not content:
            return None
        soup = BeautifulSoup(content, 'html.parser')
        container = soup.select_one('div.col-lg-9')
        if not container:
            return None
        link = container.select_one('a[href^="/d/"]')
        if link:
            m = re.search(r'/d/(\d+)', link['href'])
            if m:
                return m.group(1)
        return None

    def search(self, items, candidate=None):
        """搜索字幕"""
        if not candidate or not candidate.get('id'): return []
        if candidate.get('source') == 'imdb':
            resolved_id = self._resolve_imdb(candidate['id'])
            if not resolved_id:
                self.log(f"SubHD: IMDB {candidate['id']} not found", 2)
                return []
            candidate = {**candidate, 'id': resolved_id}
        url = f"{self.BASE_URL}/d/{candidate.get('id')}"
        content = self.get_page(url)
        if not content: return []
        episode = items.get('episode') if items.get('tvshow') else None
        results = self._parse_subtitles(content, episode)
        prod = "剧集" if candidate.get('type') == 'tv' else "电影"
        for r in results: r['tags']['production'] = prod
        return results

    def _resolve_down_url(self, page_url, soup):
        """解析临时下载页地址。

        2026-08 改版后详情页不再有 /down/ 直链，而是按钮(button.down[data-sid])，
        需先 POST /api/sub/prepare-download 换取一次性临时页 /down/{sid}
        （直连 /down/{sid} 返回 403）。旧版 <a class="down"> 直链保留为兜底。
        """
        sid = None
        btn = soup.find('button', class_='down')
        if btn:
            sid = btn.get('data-sid') or btn.get('sid')
        if not sid:
            m = re.search(r'/a/([^/?#]+)', page_url)
            sid = m.group(1) if m else None
        if sid:
            try:
                res = self.session.post(
                    self.BASE_URL + "/api/sub/prepare-download",
                    json={"sid": sid},
                    headers={'Referer': page_url, 'X-Requested-With': 'XMLHttpRequest'},
                    timeout=10)
                if res.status_code == 200:
                    data = res.json()
                    if data.get('success') and data.get('url'):
                        temp = data['url']
                        return temp if temp.startswith('http') else self.BASE_URL + temp
                    self.log(f"prepare-download failed: {data.get('msg')}", 2)
                else:
                    self.log(f"prepare-download status {res.status_code}", 2)
            except Exception as e:
                self.log(f"prepare-download exception: {e}", 2)
        for a in soup.find_all('a', class_='down'):
            href = a.get('href', '')
            if '/down/' in href:
                return href if href.startswith('http') else self.BASE_URL + href
        return None

    def download(self, url):
        """下载字幕"""
        content = self.get_page(url)
        if not content: return [], [], []
        soup = BeautifulSoup(content, 'html.parser')
        down_url = self._resolve_down_url(url, soup)
        if not down_url:
            self.log("No download entry found on page", 2)
            return [], [], []
        if not self.get_page(down_url, referer=url): return [], [], []
        sid = down_url.split('/')[-1].split('?')[0].split('#')[0]
        api_url = self.BASE_URL + "/api/sub/down"
        try:
            payload = {"sid": sid, "cap": ""}
            res = self.session.post(api_url, json=payload, headers={'Referer': down_url}, timeout=10)
            if res.status_code != 200: return [], [], []
            data = res.json()
            if data.get('pass') == False:
                svg = data.get('msg')
                if svg:
                    # IP 风控/限额时后端仍会返回 SVG 验证码(pass=false, msg=svg)。
                    # 干净 IP 难以复现，此处保持与旧版一致的求解重试逻辑
                    from .captcha import SubHDSolver
                    code = SubHDSolver().solve(svg)
                    payload["cap"] = code
                    res = self.session.post(api_url, json=payload, headers={'Referer': down_url}, timeout=10)
                    data = res.json()
            if not data.get('success'): return [], [], []
            file_url = data.get('url')
            if not file_url: return [], [], []
            if not file_url.startswith('http'): file_url = self.BASE_URL + file_url
            file_res = self.session.get(file_url, headers={'Referer': down_url}, timeout=15)
            filename = get_filename_from_cd(file_res.headers.get("Content-Disposition"), url=file_res.url or file_url, default="subtitle.bin")
            return save_and_unpack(self.DOWNLOAD_LOCATION, self.unpacker, filename, file_res.content)
        except Exception as e:
            self.log(f"Download exception: {e}", 2)
            return [], [], []
