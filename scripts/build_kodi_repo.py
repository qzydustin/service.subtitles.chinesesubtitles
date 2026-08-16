#!/usr/bin/env python3
import datetime
import hashlib
import html
import os
import shutil
import sys
import zipfile
from pathlib import Path

import markdown

ADDON_ID = "service.subtitles.chinesesubtitles"
REPO_ID = "repository.chinesesubtitles"
DIST_DIR = Path("dist")
SITE_DIR = DIST_DIR / "kodi-repo"
ZIPS_DIR = SITE_DIR / "repo" / "zips"


def read_addon_version(addon_xml):
    import xml.etree.ElementTree as ET

    root = ET.parse(addon_xml).getroot()
    return root.attrib["version"]


def clean_site_dir():
    if SITE_DIR.exists():
        shutil.rmtree(SITE_DIR)
    ZIPS_DIR.mkdir(parents=True)


def copy_addon_zip():
    version = read_addon_version("addon.xml")
    zip_name = f"{ADDON_ID}-{version}.zip"
    source = DIST_DIR / zip_name
    if not source.exists():
        raise FileNotFoundError(f"Missing add-on zip: {source}")

    target_dir = ZIPS_DIR / ADDON_ID
    target_dir.mkdir(parents=True)
    shutil.copy2(source, target_dir / zip_name)
    # the repo listing shows these next to the zip before the add-on is
    # installed (Kodi wiki: each add-on dir should contain the <assets>)
    for asset in ("resources/icon.png", "resources/fanart.jpeg"):
        shutil.copy2(asset, target_dir / Path(asset).name)


def build_repository_zip():
    version = read_addon_version(Path(REPO_ID) / "addon.xml")
    zip_name = f"{REPO_ID}-{version}.zip"
    target_dir = ZIPS_DIR / REPO_ID
    target_dir.mkdir(parents=True)

    repo_zip = target_dir / zip_name
    with zipfile.ZipFile(repo_zip, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(Path(REPO_ID).rglob("*")):
            if path.is_file():
                archive.write(path, path.as_posix())
    shutil.copy2(repo_zip, SITE_DIR / zip_name)


def addon_xml_body(path):
    content = Path(path).read_text(encoding="utf-8-sig").strip()
    if content.startswith("<?xml"):
        content = content.split("?>", 1)[1].strip()
    return content


def write_addons_xml():
    body = "\n".join(
        [
            addon_xml_body("addon.xml"),
            addon_xml_body(Path(REPO_ID) / "addon.xml"),
        ]
    )
    content = '<?xml version="1.0" encoding="UTF-8"?>\n<addons>\n%s\n</addons>\n' % body
    addons_xml = ZIPS_DIR / "addons.xml"
    addons_xml.write_text(content, encoding="utf-8")

    digest = hashlib.md5(addons_xml.read_bytes()).hexdigest()
    (ZIPS_DIR / "addons.xml.md5").write_text(digest, encoding="utf-8")


def write_index_html():
    readme = Path("README.md").read_text(encoding="utf-8")
    body = markdown.markdown(readme, extensions=["fenced_code", "nl2br", "sane_lists"])
    # this page IS the download page: drop the README's pointer to it
    # (silently kept again if the README wording ever changes)
    body = body.replace(
        '<p>也可以从<a href="https://qzydustin.github.io/service.subtitles.chinesesubtitles/">'
        '下载页面</a>直接下载。</p>', "")
    # the downloads box leads the page: split the rendered README at its
    # first section heading so the links sit right after the intro
    intro, sep, sections = body.partition("<h2")
    sections = sep + sections

    repo_version = read_addon_version(Path(REPO_ID) / "addon.xml")
    addon_version = read_addon_version("addon.xml")
    repo_zip = f"{REPO_ID}-{repo_version}.zip"
    addon_zip = f"repo/zips/{ADDON_ID}/{ADDON_ID}-{addon_version}.zip"
    # Kodi's HTTPS directory browser lists this very page's anchors, but
    # only accepts those whose link text equals the href (HTTPDirectory's
    # NameMatchesLink) — the zip filenames must stay the anchor text, and
    # human annotations ride along outside the <a>. Kodi fetches
    # addons.xml/addons.xml.md5 by URL from the repository add-on's own
    # addon.xml, so the page needs no link to them
    downloads = """<h2>下载</h2>
<ul>
  <li><a href="{repo_zip}">{repo_zip}</a>（推荐，可自动接收更新）</li>
  <li><a href="{addon_zip}">{addon_name}</a>（直接安装当前版本，更新需重装）</li>
</ul>
""".format(
        repo_zip=html.escape(repo_zip),
        addon_zip=html.escape(addon_zip),
        addon_name=html.escape(f"{ADDON_ID}-{addon_version}.zip"),
    )

    content = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ChineseSub</title>
  <meta name="description" content="Kodi 中文字幕插件 ChineseSub：从 SubHD 和 Zimuku 搜索下载字幕。">
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      line-height: 1.7;
      color: #333;
      background: #f7f8fa;
      padding: 2rem 1rem;
    }
    .container {
      max-width: 800px;
      margin: 0 auto;
      background: #fff;
      border-radius: 12px;
      box-shadow: 0 2px 12px rgba(0,0,0,0.08);
      padding: 3rem;
    }
    h1 { font-size: 2rem; margin-bottom: 0.5rem; color: #1a1a2e; }
    h2 { font-size: 1.4rem; margin-top: 2rem; margin-bottom: 0.8rem; color: #1a1a2e; border-bottom: 2px solid #e8e8e8; padding-bottom: 0.3rem; }
    p, li { margin-bottom: 0.6rem; }
    ul, ol { padding-left: 1.5rem; }
    a { color: #2563eb; text-decoration: none; }
    a:hover { text-decoration: underline; }
    pre {
      background: #f4f4f8;
      border: 1px solid #e2e2e8;
      border-radius: 6px;
      padding: 1rem;
      overflow-x: auto;
      white-space: pre-wrap;
      word-wrap: break-word;
      font-size: 0.9rem;
      margin: 0.8rem 0;
    }
    code {
      font-family: "SFMono-Regular", Consolas, "Liberation Mono", Menlo, monospace;
      font-size: 0.9em;
    }
    :not(pre) > code {
      background: #f0f0f5;
      padding: 0.15rem 0.4rem;
      border-radius: 4px;
    }
    .downloads {
      margin-top: 2rem;
      background: #f0f7ff;
      border: 1px solid #d0e3f7;
      border-radius: 8px;
      padding: 1.5rem;
    }
    .downloads h2 { border-bottom: none; margin-top: 0; color: #1a4a7a; }
    .downloads li { margin-bottom: 0.6rem; }
    footer {
      text-align: center;
      margin-top: 2rem;
      font-size: 0.85rem;
      color: #999;
    }
  </style>
</head>
<body>
<div class="container">
{{INTRO}}
<div class="downloads">
{{DOWNLOADS}}
</div>
{{SECTIONS}}
<footer><a href="https://github.com/qzydustin/service.subtitles.chinesesubtitles">GitHub</a> &middot; ChineseSubtitles &copy; {{YEAR}}</footer>
</div>
</body>
</html>
"""
    # placeholder replace, not %-format: the CSS must stay free to use %
    content = (content
               .replace("{{INTRO}}", intro)
               .replace("{{SECTIONS}}", sections)
               .replace("{{DOWNLOADS}}", downloads)
               .replace("{{YEAR}}", str(datetime.date.today().year)))
    (SITE_DIR / "index.html").write_text(content, encoding="utf-8")


def main():
    os.chdir(Path(__file__).resolve().parents[1])
    clean_site_dir()
    copy_addon_zip()
    build_repository_zip()
    write_addons_xml()
    write_index_html()
    print(f"Built Kodi repository at {SITE_DIR}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Failed to build Kodi repository: {exc}", file=sys.stderr)
        sys.exit(1)
