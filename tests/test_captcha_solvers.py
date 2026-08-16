# -*- coding: utf-8 -*-
"""Offline tests: Zimuku's BMP captcha solver and the SubHD download flow.

Site captchas only appear under IP throttling, so live tests cannot cover
them reliably; synthetic samples keep the logic and wiring intact.
"""
import base64
import io
import os
import struct
import sys
import tempfile
import zipfile

base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
lib_dir = os.path.join(base_dir, "resources", "lib")
if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

from core.subhd import SubhdProvider
from core.zimuku import ZimukuProvider, ZimukuSolver


_ZIMUKU_POINTS = [(10, 7), (7, 8), (12, 8), (10, 13), (7, 19), (12, 19), (10, 20), (6, 13), (14, 13)]


def _bmp_with_digits(painted_per_char):
    """[(char_index, painted_point_indices)] -> synthetic captcha BMP.

    Painting the template's 1-points black makes template matching hit that digit.
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
    # '0' [1,1,1,1,1,1,1,1,0]; '7' [1,0,1,0,0,0,0,0,0]; '3' [1,0,1,1,0,1,1,0,0]
    b64 = _bmp_with_digits([(0, range(8)), (1, (0, 2)), (2, (0, 2, 3, 5, 6))])
    text = ZimukuSolver(b64).recognize()
    # trailing unpainted chars are unstable; no '1'/'4' in the first three
    # so the narrow-glyph offset stays zero
    assert text[:3] == "073", text


def _zip_bytes(name, content=b"[Script Info]\n"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, content)
    return buf.getvalue()


class _Resp:
    def __init__(self, status_code=200, json_data=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_data or {}
        self.content = content
        self.headers = headers or {}
        self.url = ""

    def json(self):
        return self._json


class _FakeSession:
    """Replays the SubHD download flow: detail -> prepare -> (refusal) -> file."""

    def __init__(self, file_content, file_cd, refuse=False):
        self.file_content = file_content
        self.file_cd = file_cd
        self.refuse = refuse
        self.down_payloads = []

    def get(self, url, headers=None, timeout=None):
        if "/a/" in url:
            detail = ('<button class="btn btn-danger down subtitle-prepare-download"'
                      ' data-sid="TEST1">下载字幕文件</button>')
            return _Resp(content=detail.encode())
        if "/down/" in url:
            return _Resp(content=b"<html>temp</html>")
        return _Resp(content=self.file_content, headers={"Content-Disposition": self.file_cd})

    def post(self, url, json=None, headers=None, timeout=None):
        if "prepare-download" in url:
            return _Resp(json_data={"success": True, "url": "/down/TEST1"})
        self.down_payloads.append(dict(json))
        if self.refuse and len(self.down_payloads) == 1:
            return _Resp(json_data={"success": False, "pass": False,
                                    "msg": "下载频率过高，请不要再试", "url": None})
        return _Resp(json_data={"success": True, "pass": True, "url": "https://dl.subhd.me/x.zip"})


def test_subhd_download_throttle_refusal():
    # measured 2026-08: throttling answers with plain text, the old-site SVG
    # captcha is gone; the one-time temp page is spent, so no retry may happen
    session = _FakeSession(file_content=_zip_bytes("x.ass"),
                           file_cd='attachment; filename="cap.zip"', refuse=True)
    with tempfile.TemporaryDirectory() as dest:
        provider = SubhdProvider()
        provider.session = session
        result = provider.download("https://subhd.tv/a/TEST1", dest)
    assert len(session.down_payloads) == 1, "must not retry a refusal"
    assert result.status == "failed"
    assert "下载频率过高" in result.reason


def test_subhd_download_invalid_file_has_no_kodi_dependency():
    # a non-subtitle payload must surface as status='invalid' without xbmc
    session = _FakeSession(file_content=b"NOT A SUBTITLE", file_cd='attachment; filename="note.bin"')
    with tempfile.TemporaryDirectory() as dest:
        provider = SubhdProvider()
        provider.session = session
        result = provider.download("https://subhd.tv/a/TEST1", dest)
    assert result.status == "invalid"
    assert result.files == []
