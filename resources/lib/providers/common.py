import os
import re
import html
import urllib.parse

from constants import DEFAULT_UA, DEFAULT_HEADERS, SUBTITLE_EXTS, ARCHIVE_EXTS  # noqa: F401  re-export

SRC_MAP = {
    'official': "[官方]",
    'reprint': "[精修]",
    'original': "[原创]",
    'ai': "[AI]",
    'machine': "[机翻]",
}

FMT_MAP = {
    'ass': "[ASS]",
    'srt': "[SRT]",
    'ssa': "[SSA]",
    'sub': "[SUB]",
    'sup': "[SUP]",
    'vtt': "[VTT]",
}


def make_session(retries=3):
    """创建带统一浏览器头与重试策略的 HTTP 会话。"""
    import requests
    session = requests.Session()
    session.headers.update({'User-Agent': DEFAULT_UA, **DEFAULT_HEADERS})
    if retries:
        adapter = requests.adapters.HTTPAdapter(max_retries=retries)
        session.mount('https://', adapter)
        session.mount('http://', adapter)
    return session

def get_filename_from_cd(cd, url=None, default=None):
    if cd:
        cd = cd.strip()
        fname_star = re.findall(r"filename\*\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if fname_star:
            raw = fname_star[0].strip().strip('"').strip("'")
            if "''" in raw:
                raw = raw.split("''", 1)[1]
            return html.unescape(urllib.parse.unquote(raw))
        fname = re.findall(r"filename\s*=\s*(\".*?\"|[^;]+)", cd, flags=re.IGNORECASE)
        if fname:
            return html.unescape(fname[0].strip().strip('"').strip("'"))
    if url:
        parsed = urllib.parse.urlparse(url)
        tail = os.path.basename(parsed.path)
        if tail:
            return tail
    return default

def _shorten_filenames(sub_name_list):
    if len(sub_name_list) > 1:
        try:
            shortest_fn = min(sub_name_list, key=len)
            diff_index = next(filter(
                lambda i: any(s[i] != shortest_fn[i] for s in sub_name_list),
                range(len(shortest_fn))
            ), len(shortest_fn))
            dot = shortest_fn[:diff_index].rfind('.') + 1
            return [s[dot:] for s in sub_name_list]
        except Exception:
            return sub_name_list
    return sub_name_list

def _lang_label(tags):
    langs = set(tags.get('lang', []))
    parts = []
    if 'chs' in langs: parts.append('简')
    if 'cht' in langs: parts.append('繁')
    if 'eng' in langs: parts.append('英')
    if not parts:
        return ""
    return "[" + "".join(parts) + "]"

def build_subtitle_label(tags, provider=None, filename=None):
    final_label = ""
    if provider: final_label += f"[{provider}]"
    prod = tags.get('production')
    if prod: final_label += f"[{prod}]"
    final_label += _lang_label(tags)
    for key, label in SRC_MAP.items():
        if key in tags.get('source', []):
            final_label += label
            break
    for key, label in FMT_MAP.items():
        if key in tags.get('fmt', []):
            final_label += label
            break
    if tags.get('collection'): final_label += "[合集]"
    fansub = tags.get('fansub')
    if fansub: final_label += f"[{fansub}]"
    if filename: final_label += f" {filename}"
    return final_label

def save_and_unpack(download_location, unpacker, filename, data):
    filename = os.path.basename(filename)
    filepath = os.path.join(download_location, filename)
    with open(filepath, 'wb') as f:
        f.write(data)
    target_path, files = unpacker.unpack(filepath)
    if not files:
        if not filepath.lower().endswith(SUBTITLE_EXTS):
            try:
                import xbmcaddon, xbmcgui
                addon = xbmcaddon.Addon()
                icon = os.path.join(addon.getAddonInfo('path'), 'resources', 'icon.png')
                xbmcgui.Dialog().notification(
                    addon.getAddonInfo('name'), addon.getLocalizedString(30902), icon, 4000)
            except Exception:
                pass  # 无 Kodi 环境（测试/headless）时跳过通知
            return [], [], []
        return [filename], [filename], [filepath]
    full_paths = [os.path.join(target_path, f) for f in files]
    short_sub_name_list = _shorten_filenames(files)
    return files, short_sub_name_list, full_paths
