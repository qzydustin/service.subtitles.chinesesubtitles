# -*- coding: utf-8 -*-
"""验证码求解与 SubHD 验证码重试链路的离线测试（不联网）。

外部站点的验证码只在 IP 风控/限额时出现，联网测试难以稳定复现，
因此用合成样本保证求解逻辑与下载重试分支不被改坏。
"""
import base64
import os
import struct
import sys
import tempfile
import types

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)


def _install_xbmc_stubs():
    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG = xbmc.LOGINFO = xbmc.LOGWARNING = xbmc.LOGERROR = 0
    sys.modules.setdefault("xbmc", xbmc)
    xbmcvfs = types.ModuleType("xbmcvfs")
    xbmcvfs.translatePath = lambda p: p
    xbmcvfs.exists = lambda p: os.path.exists(p)
    xbmcvfs.mkdirs = lambda p: os.makedirs(p, exist_ok=True)
    xbmcvfs.delete = lambda p: os.remove(p) if os.path.exists(p) else None
    xbmcvfs.listdir = lambda p: (os.listdir(p), [])
    xbmcvfs.rmdir = lambda p: os.rmdir(p) if os.path.isdir(p) else None
    sys.modules.setdefault("xbmcvfs", xbmcvfs)
    xbmcgui = types.ModuleType("xbmcgui")
    xbmcgui.Dialog = types.SimpleNamespace(
        select=lambda *a, **k: 0, notification=lambda *a, **k: None)
    sys.modules.setdefault("xbmcgui", xbmcgui)
    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = lambda: types.SimpleNamespace(
        getAddonInfo=lambda k: "", getSetting=lambda k: "false",
        getLocalizedString=lambda k: "")
    sys.modules.setdefault("xbmcaddon", xbmcaddon)


_install_xbmc_stubs()


class _Logger:
    def log(self, module, msg, level=0):
        pass


# ---- SubHD SVG 求解器 ----

def _svg_with_paths(spec):
    """spec: [(start_x, path_len)]，生成包含对应长度 d 属性的合成 SVG。

    求解器按 path 字符串长度查 LENGTH_MAP、按起始 x 排序，并过滤 <=500 的噪声 path。
    """
    paths = []
    for x, length in spec:
        d = "M%d 1" % x
        d += "9" * (length - len(d))
        assert len(d) == length
        paths.append('<path d="%s"/>' % d)
    return "<svg>" + "".join(paths) + "</svg>"


def test_subhd_solver_known_lengths():
    from providers.subhd.captcha import SubHDSolver
    # (start_x, 长度) -> LENGTH_MAP 首选字符: 998->'1', 2246->'E', 2606->'5', 3033->'9'
    # 额外放一条短噪声 path(长度 100)，验证被过滤
    svg = _svg_with_paths([(5, 100), (10, 998), (30, 2246), (50, 2606), (70, 3033)])
    assert SubHDSolver().solve(svg) == "1E59"


# ---- Zimuku BMP 求解器 ----

_ZIMUKU_POINTS = [(10, 7), (7, 8), (12, 8), (10, 13), (7, 19), (12, 19), (10, 20), (6, 13), (14, 13)]


def _bmp_with_digits(painted_per_char):
    """painted_per_char: [(字符位序号, 要涂黑的采样点索引)]，其余像素为背景色。

    模板中值为 1 的采样点涂黑、值为 0 的保持背景，即可让模板匹配命中该数字。
    """
    W, H, STRIDE = 100, 27, 300
    buf = bytearray(b"\xff" * (54 + STRIDE * H))
    struct.pack_into("<2sIHHI", buf, 0, b"BM", len(buf), 0, 0, 54)
    struct.pack_into("<IiiHHIIiiII", buf, 14, 40, W, H, 1, 24, 0, STRIDE * H, 0, 0, 0, 0)
    for char_idx, painted in painted_per_char:
        for pt_idx in painted:
            px, py = _ZIMUKU_POINTS[pt_idx]
            x, y = char_idx * 20 + px, py
            offset = 54 + (H - 1 - y) * STRIDE + x * 3
            buf[offset:offset + 3] = b"\x00\x00\x00"
    return base64.b64encode(bytes(buf)).decode()


def test_zimuku_solver_template_match():
    from providers.zimuku.captcha import ZimukuSolver
    # '0' 模板 [1,1,1,1,1,1,1,1,0]; '7' [1,0,1,0,0,0,0,0,0]; '3' [1,0,1,1,0,1,1,0,0]
    b64 = _bmp_with_digits([
        (0, range(8)),
        (1, (0, 2)),
        (2, (0, 2, 3, 5, 6)),
    ])
    text = ZimukuSolver(b64).recognize()
    # 前三位不含 '1'/'4'（不触发窄字符偏移），后两位未涂黑、值不稳定，不做断言
    assert text[:3] == "073", text


# ---- SubHD 下载的验证码重试链路（mock 会话） ----

def test_subhd_download_captcha_retry():
    from providers.subhd import SubHDAgent

    svg = _svg_with_paths([(10, 998), (30, 2246), (50, 2606)])
    expected_cap = "1E5"
    detail_html = ('<button class="btn btn-danger down subtitle-prepare-download"'
                   ' data-sid="TEST1">下载字幕文件</button>')
    calls = {"down_posts": 0}

    class Resp:
        def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
            self.status_code = status_code
            self._json = json_data or {}
            self.content = content
            self.headers = headers or {}
            self.url = ""

        def json(self):
            return self._json

    class FakeSession:
        def get(self, url, headers=None, timeout=None):
            if "/a/" in url:
                return Resp(content=detail_html.encode())
            if "/down/" in url:
                return Resp(content=b"<html>temp</html>")
            return Resp(content=b"PKstub",
                        headers={"Content-Disposition": 'attachment; filename="cap.zip"'})

        def post(self, url, json=None, headers=None, timeout=None):
            if "prepare-download" in url:
                return Resp(json_data={"success": True, "url": "/down/TEST1"})
            calls["down_posts"] += 1
            if calls["down_posts"] == 1:
                # 首次命中风控: pass=false + SVG 验证码
                return Resp(json_data={"success": False, "pass": False, "msg": svg, "url": None})
            assert json.get("cap") == expected_cap, "重试请求未携带验证码求解结果: %r" % (json,)
            return Resp(json_data={"success": True, "pass": True, "url": "https://dl.subhd.me/x.zip"})

    class Unpacker:
        def unpack(self, path):
            return os.path.dirname(path), [os.path.basename(path)]

    with tempfile.TemporaryDirectory() as tmp:
        agent = SubHDAgent(None, tmp, _Logger(), Unpacker())
        agent.session = FakeSession()
        files, _, full = agent.download("https://subhd.tv/a/TEST1")
        assert calls["down_posts"] == 2, "验证码重试未按预期发生"
        assert files == ["cap.zip"], files
        assert full and os.path.exists(full[0])
