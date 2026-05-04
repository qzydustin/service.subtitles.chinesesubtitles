import os
import re
import html
import urllib.parse

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

SUBTITLE_EXTS = (".srt", ".sub", ".smi", ".ssa", ".ass", ".sup")
ARCHIVE_EXTS = (".zip", ".7z", ".tar", ".bz2", ".rar", ".gz", ".xz", ".iso", ".tgz", ".tbz2", ".cbr")

DEFAULT_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
DEFAULT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1'
}

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
    """根据语言标签生成简/繁/英标注"""
    langs = set(tags.get('lang', []))
    is_bilingual = tags.get('bilingual', False)
    if 'chs' in langs and 'cht' in langs:
        base = "[简繁]"
    elif 'chs' in langs:
        base = "[简]"
    elif 'cht' in langs:
        base = "[繁]"
    elif 'eng' in langs:
        base = "[英]"
    else:
        base = ""
    if is_bilingual and 'eng' in langs and base not in ("", "[英]"):
        base = base[:-1] + "英]"
    return base

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

def _is_fake_subtitle(filepath):
    """检测是否为虚假字幕（< 10KB 且包内无有效字幕文件）"""
    import os as _os, urllib.parse, xbmcvfs
    ext = filepath.lower()
    try:
        if _os.path.getsize(filepath) >= 10240:
            return False
    except Exception:
        return False
    # 直接是字幕格式
    if ext.endswith(SUBTITLE_EXTS):
        return False
    # 压缩包：用 VFS 列出内容，检查是否有字幕文件
    if ext.endswith(('.zip', '.rar', '.7z')):
        path = filepath.replace('\\', '/')
        real = xbmcvfs.translatePath(path)
        enc = urllib.parse.quote_plus(real)
        proto = 'archive' if ext.endswith('.7z') else ext[1:]
        vfs_url = f"{proto}://{enc}"
        try:
            dirs, files = xbmcvfs.listdir(vfs_url)
            if any(f.lower().endswith(SUBTITLE_EXTS) for f in files):
                return False
            # drill into subdirectory
            if not files and dirs:
                dirs2, files2 = xbmcvfs.listdir(vfs_url + '/' + dirs[0])
                if any(f.lower().endswith(SUBTITLE_EXTS) for f in files2):
                    return False
        except Exception:
            pass
    return True


def save_and_unpack(download_location, unpacker, filename, data):
    filepath = os.path.join(download_location, filename)
    with open(filepath, 'wb') as f:
        f.write(data)
    target_path, files = unpacker.unpack(filepath)
    if not files:
        if _is_fake_subtitle(filepath):
            import xbmcaddon, xbmcgui
            icon = os.path.join(xbmcaddon.Addon().getAddonInfo('path'), 'resources', 'icon.png')
            xbmcgui.Dialog().notification(
                '字幕下载', '此字幕非有效字幕文件或实际字幕文件需到网盘下载，请选择其他字幕',
                icon, 4000)
            return [], [], []  # 不返回无效项目，保持下载窗口打开
        return [filename], [filename], [filepath]
    full_paths = [target_path + '/' + f for f in files]
    short_sub_name_list = _shorten_filenames(files)
    return files, short_sub_name_list, full_paths
