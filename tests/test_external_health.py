#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部服务健康检查（轻量冒烟测试）

插件依赖三个不受我们控制的外部服务：豆瓣（候选搜索）、SubHD、Zimuku。
本脚本用最小请求逐一确认它们当前是否可用、站点改版后解析是否仍成立，
用于快速排查「字幕源是不是又挂了」这类反馈。

用法：
    python3 tests/test_external_health.py              # 轻量检查（不下载字幕文件）
    python3 tests/test_external_health.py --full       # 含完整字幕下载与解压
    python3 tests/test_external_health.py --only subhd/download-api

pytest 兼容：
    pytest tests/test_external_health.py -k light      # 轻量
    CHINESESUB_FULL=1 pytest tests/test_external_health.py   # 全量
"""
import argparse
import os
import sys
import tempfile
import time
import types

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LIB_DIR = os.path.join(BASE_DIR, "resources", "lib")
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)


def _install_xbmc_stubs():
    """本脚本只验证网络链路，用最小桩替代 Kodi 运行时。"""
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

    class _Dialog:
        @staticmethod
        def select(*args, **kwargs):
            return 0  # headless 下默认选第一项，与 candidate_service 的兜底一致

        @staticmethod
        def notification(*args, **kwargs):
            pass

    xbmcgui.Dialog = _Dialog
    sys.modules.setdefault("xbmcgui", xbmcgui)

    xbmcaddon = types.ModuleType("xbmcaddon")
    xbmcaddon.Addon = lambda: types.SimpleNamespace(
        getAddonInfo=lambda k: "",
        getSetting=lambda k: "false",
        getLocalizedString=lambda k: "",
    )
    sys.modules.setdefault("xbmcaddon", xbmcaddon)


_install_xbmc_stubs()


class _Logger:
    def log(self, module, msg, level=0):
        pass


class _Unpacker:
    def __init__(self):
        import archive_utils
        self._archive_utils = archive_utils

    def unpack(self, path):
        try:
            return self._archive_utils.unpack(path, logger=_Logger())
        except Exception:
            return path, []


# 固定样本：盗梦空间（2010）。各检查相互独立，不依赖其他检查的结果。
DOUBAN_QUERY = "盗梦空间"
SUBHD_DOUBAN_ID = "3541415"   # 盗梦空间在 SubHD 以豆瓣 ID 作为作品页 ID
SUBHD_SID = "HbupDV"          # 一个长期存在的字幕条目
ZIMUKU_QUERY = "盗梦空间"

CHECKS = []  # (name, func, full_only)


def check(name, full=False):
    def deco(fn):
        CHECKS.append((name, fn, full))
        return fn
    return deco


def _make_agents():
    from providers.registry import build_agents
    return build_agents(tempfile.mkdtemp(), _Logger(), _Unpacker())


@check("douban/search")
def check_douban():
    import douban_agent
    candidates = douban_agent.get_agent().search(title=DOUBAN_QUERY)
    assert candidates, "豆瓣搜索无结果"
    first = candidates[0]
    return "%d 个候选，如: %s (%s)" % (len(candidates), first.get("title"), first.get("year"))


@check("subhd/search")
def check_subhd_search():
    agent = _make_agents()["subhd"]
    results = agent.search(
        {"year": "2010", "title": "盗梦空间"},
        candidate={"id": SUBHD_DOUBAN_ID, "type": "movie"},
    )
    assert results, "SubHD 作品页解析不到字幕（站点可能改版）"
    return "%d 条字幕 (/d/%s)" % (len(results), SUBHD_DOUBAN_ID)


@check("subhd/download-api")
def check_subhd_download_api():
    """验证 SubHD 2025 改版后的关键链路：prepare-download 能换取临时下载页。"""
    from providers.common import make_session
    session = make_session(retries=0)
    detail = "https://subhd.tv/a/%s" % SUBHD_SID
    session.get(detail, timeout=10)
    res = session.post(
        "https://subhd.tv/api/sub/prepare-download",
        json={"sid": SUBHD_SID},
        headers={"Referer": detail, "X-Requested-With": "XMLHttpRequest"},
        timeout=10,
    )
    assert res.status_code == 200, "HTTP %s" % res.status_code
    data = res.json()
    assert data.get("success") and data.get("url"), "API 返回异常: %r" % (data,)
    return "prepare-download -> %s" % data["url"]


@check("zimuku/search")
def check_zimuku_search():
    agent = _make_agents()["zimuku"]
    candidates = agent.search_candidates(ZIMUKU_QUERY, "2010", is_tv=False)
    assert candidates, "Zimuku 搜索无结果（含验证码自动重试后仍失败）"
    return "%d 个候选，如: %s" % (len(candidates), candidates[0].get("title"))


@check("subhd/download", full=True)
def check_subhd_download():
    agent = _make_agents()["subhd"]
    results = agent.search(
        {"year": "2010", "title": "盗梦空间"},
        candidate={"id": SUBHD_DOUBAN_ID, "type": "movie"},
    )
    assert results, "搜索无结果"
    files, _, _ = agent.download(results[0]["link"])
    assert files, "下载失败（prepare-download -> 临时页 -> /api/sub/down 链路未走通）"
    return "下载并解压 %d 个文件，如: %s" % (len(files), files[0])


@check("zimuku/download", full=True)
def check_zimuku_download():
    agent = _make_agents()["zimuku"]
    candidates = agent.search_candidates(ZIMUKU_QUERY, "2010", is_tv=False)
    assert candidates, "候选搜索无结果"
    selected = dict(candidates[0])
    selected.setdefault("type", "movie")
    results = agent.search({"year": "2010", "title": ZIMUKU_QUERY}, candidate=selected)
    assert results, "搜索无结果"
    files, _, _ = agent.download(results[0]["link"])
    assert files, "下载失败"
    return "下载并解压 %d 个文件，如: %s" % (len(files), files[0])


def run(full=False, only=None):
    if only and not any(name == only for name, _, _ in CHECKS):
        print("未知检查: %s" % only)
        print("可用检查: %s" % ", ".join(name for name, _, _ in CHECKS))
        return 1

    rows, failures = [], 0
    for name, fn, full_only in CHECKS:
        if only:
            # 显式点名时直接运行（包括完整模式检查），不受 --full 限制
            if only != name:
                continue
        elif full_only and not full:
            continue
        start = time.time()
        try:
            detail = fn()
            rows.append((name, True, "%.1fs  %s" % (time.time() - start, detail)))
        except Exception as e:
            failures += 1
            rows.append((name, False, "%.1fs  %s: %s" % (time.time() - start, type(e).__name__, e)))

    mode = "完整" if full else "轻量"
    print("\n外部服务健康检查 (%s)  %s" % (mode, time.strftime("%Y-%m-%d %H:%M:%S")))
    print("-" * 72)
    width = max([len(n) for n, _, _ in rows] + [10])
    for name, ok, detail in rows:
        print("[%-4s] %-*s  %s" % ("OK" if ok else "FAIL", width, name, detail))
    print("-" * 72)
    print("%d/%d 通过" % (len(rows) - failures, len(rows)))
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="外部字幕源健康检查")
    parser.add_argument("--full", action="store_true", help="包含完整字幕下载与解压")
    parser.add_argument("--only", help="只运行指定检查（如 subhd/download-api）")
    args = parser.parse_args()
    sys.exit(min(run(full=args.full, only=args.only), 1))


# ---- pytest 兼容入口 ----

def test_external_services_light():
    assert run(full=False) == 0


def test_external_services_full():
    if os.environ.get("CHINESESUB_FULL") != "1":
        import pytest
        pytest.skip("设置 CHINESESUB_FULL=1 启用完整下载检查")
    assert run(full=True) == 0
