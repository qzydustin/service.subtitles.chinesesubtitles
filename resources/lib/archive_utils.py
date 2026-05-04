# -*- coding: utf-8 -*-
import os
import urllib.parse
import xbmcvfs

class _NullLogger:
    def log(self, *args, **kwargs):
        pass


def _decode_cjk(raw_bytes):
    """纯 Python GBK 解码，用于无 CJK codec 的环境（CoreELEC 等）"""
    try:
        from _gbk_table import decode_gbk
        return decode_gbk(raw_bytes)
    except ImportError:
        return None


def _decode_zip_filename(name, flag_bits, raw_bytes=None):
    """自动检测 ZIP 文件名编码，不依赖 cp437 编解码器"""
    if flag_bits & 0x800:
        return name
    if raw_bytes is None:
        # 回退：尝试 cp437 逆向（可能不可用）
        try:
            raw_bytes = name.encode('cp437')
        except Exception:
            return name
    # 优先尝试内置 codec（Windows/macOS 上 gb18030 可用）
    try:
        decoded = raw_bytes.decode('gb18030')
        if any('一' <= c <= '鿿' for c in decoded):
            return decoded
    except (LookupError, UnicodeDecodeError):
        pass
    # 回退：纯 Python GBK 解码器（CoreELEC 等无 CJK codec 的环境）
    decoded = _decode_cjk(raw_bytes)
    if decoded is not None and any('一' <= c <= '鿿' for c in decoded):
        return decoded
    return name


def _list_zip_via_python(real_path, logger):
    """用 Python zipfile 列出 ZIP 并提取字幕，修复文件名编码"""
    import zipfile
    import struct
    exts = (".srt", ".sub", ".ssa", ".ass", ".sup", ".vtt")
    try:
        zf = zipfile.ZipFile(real_path, 'r')
        # 从 ZIP 文件头直接读原始文件名字节，不依赖 cp437 编解码器
        raw_names = {}
        with open(real_path, 'rb') as f:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                # 本地文件头: offset 26=filename_length(2B), 28=extra_length(2B), 30=filename
                f.seek(info.header_offset + 26)
                fn_len = struct.unpack('<H', f.read(2))[0]
                f.read(2)  # 跳过 extra_field_length
                raw = f.read(fn_len)
                raw_names[info.filename] = raw
        entries = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = raw_names.get(info.filename, None)
            display_name = _decode_zip_filename(info.filename, info.flag_bits, raw_bytes=raw)
            if display_name.lower().endswith(exts):
                entries.append((display_name, info.filename))
        if not entries:
            zf.close()
            return None, []

        extract_dir = real_path + '.extracted'
        os.makedirs(extract_dir, exist_ok=True)
        result = []
        for display_name, raw_name in entries:
            dest = os.path.join(extract_dir, os.path.basename(display_name))
            with zf.open(raw_name) as src:
                with open(dest, 'wb') as dst:
                    dst.write(src.read())
            result.append(os.path.basename(display_name))

        zf.close()
        logger.log("archive_utils", "zipfile extracted %d files (encoding fix)" % len(result))
        return extract_dir, result
    except Exception as e:
        logger.log("archive_utils", "zipfile fallback error: %s" % e, 2)
        return None, []


def unpack(file_path, logger=None):
    """
    Get the file list from archive file.
    Supports zip, rar.
    """
    exts = (".srt", ".sub", ".ssa", ".ass", ".sup", ".vtt")
    supported_archive_exts = (".zip", ".rar", ".7z")

    logger = logger or _NullLogger()

    if not file_path.endswith(supported_archive_exts):
        logger.log("archive_utils", "Unsupported file ext: %s" % os.path.basename(file_path), 2)
        return '', []

    file_path = file_path.replace('\\', '/').rstrip('/')

    real_path = xbmcvfs.translatePath(file_path)
    archive_url = urllib.parse.quote_plus(real_path)
    ext = file_path.split('.')[-1]

    if ext == '7z':
        vfs_protocol = 'archive'
    else:
        vfs_protocol = ext

    vfs_url = f"{vfs_protocol}://{archive_url}"

    logger.log("archive_utils", "Unpacking: %s" % vfs_url)

    try:
        dirs, files = xbmcvfs.listdir(vfs_url)

        # ZIP: 用 Python zipfile 修复中文编码
        if ext == 'zip':
            extract_dir, fixed = _list_zip_via_python(real_path, logger)
            if fixed:
                return extract_dir, fixed

        if '__MACOSX' in dirs:
            dirs.remove('__MACOSX')

        target_path = vfs_url
        if not any(f.lower().endswith(exts) for f in files) and dirs:
            target_path = vfs_url + '/' + dirs[0]
            dirs, files = xbmcvfs.listdir(target_path)

        subtitle_list = [f for f in files if f.lower().endswith(exts)]

        return target_path, subtitle_list

    except Exception as e:
        logger.log("archive_utils", "Unpack error: %s" % e, 2)
        return '', []
