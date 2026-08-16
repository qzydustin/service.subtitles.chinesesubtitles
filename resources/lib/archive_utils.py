# -*- coding: utf-8 -*-
import os
import urllib.parse
import xbmcvfs

from constants import SUBTITLE_EXTS


class _NullLogger:
    def log(self, *args, **kwargs):
        pass


def _unpack_zip(real_path, logger):
    """Extract ZIP with Python zipfile, fixing CJK filenames if needed."""
    import zipfile
    from _gbk_codec import fix_zip_filename
    try:
        with zipfile.ZipFile(real_path, 'r') as zf:
            entries = []
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename if (info.flag_bits & 0x800) else fix_zip_filename(info.filename)
                name = os.path.basename(name)
                if name.lower().endswith(SUBTITLE_EXTS):
                    entries.append((name, info))
            if not entries:
                return None, []

            extract_dir = real_path + '_extracted'
            os.makedirs(extract_dir, exist_ok=True)
            result = []
            for name, info in entries:
                with zf.open(info) as src, open(os.path.join(extract_dir, name), 'wb') as dst:
                    dst.write(src.read())
                result.append(name)
            return extract_dir, result
    except Exception as e:
        logger.log("archive_utils", "ZIP extract failed: %s" % e, 2)
        return None, []


def unpack(file_path, logger=None):
    """
    Get the file list from archive file.
    Supports zip, rar, 7z.
    """
    supported_archive_exts = (".zip", ".rar", ".7z")

    logger = logger or _NullLogger()

    if not file_path.endswith(supported_archive_exts):
        logger.log("archive_utils", "Unsupported file ext: %s" % os.path.basename(file_path), 2)
        return '', []

    file_path = file_path.replace('\\', '/').rstrip('/')
    real_path = xbmcvfs.translatePath(file_path)
    ext = file_path.split('.')[-1]

    if ext == 'zip':
        return _unpack_zip(real_path, logger)

    vfs_protocol = 'archive' if ext == '7z' else ext
    archive_url = urllib.parse.quote_plus(real_path)
    vfs_url = f"{vfs_protocol}://{archive_url}"

    logger.log("archive_utils", "Unpacking: %s" % vfs_url)

    try:
        dirs, files = xbmcvfs.listdir(vfs_url)

        if '__MACOSX' in dirs:
            dirs.remove('__MACOSX')

        target_path = vfs_url
        if not any(f.lower().endswith(SUBTITLE_EXTS) for f in files) and dirs:
            target_path = vfs_url + '/' + dirs[0]
            dirs, files = xbmcvfs.listdir(target_path)

        subtitle_list = [f for f in files if f.lower().endswith(SUBTITLE_EXTS)]

        return target_path, subtitle_list

    except Exception as e:
        logger.log("archive_utils", "Unpack error: %s" % e, 2)
        return '', []
