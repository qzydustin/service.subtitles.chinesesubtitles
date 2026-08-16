# -*- coding: utf-8 -*-
"""全局共享常量（不依赖 Kodi / xbmc，可安全在无 Kodi 环境导入）。"""

DEFAULT_UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

DEFAULT_HEADERS = {
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Cache-Control': 'no-cache',
    'Pragma': 'no-cache',
    'Upgrade-Insecure-Requests': '1'
}

# 历史上 providers/common.py 与 archive_utils.py 各维护一份且不一致
# （一个含 smi 缺 vtt，一个含 vtt 缺 smi），此处取并集作为唯一定义。
SUBTITLE_EXTS = (".srt", ".sub", ".smi", ".ssa", ".ass", ".sup", ".vtt")

ARCHIVE_EXTS = (".zip", ".7z", ".tar", ".bz2", ".rar", ".gz", ".xz", ".iso", ".tgz", ".tbz2", ".cbr")
