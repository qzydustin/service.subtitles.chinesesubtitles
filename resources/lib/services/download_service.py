import os

import xbmcgui
import xbmcvfs


def _prepare_temp_dir(temp_dir, logger):
    temp_dir = temp_dir.replace("\\", "/").rstrip("/")
    if not xbmcvfs.exists(temp_dir):
        xbmcvfs.mkdirs(temp_dir)
        return

    def child_path(parent, name):
        return os.path.join(parent, name).replace("\\", "/")

    def remove_contents(path):
        try:
            dirs, files = xbmcvfs.listdir(path)
        except Exception as e:
            logger.log("Download", "Failed to list temp dir %s: %s" % (path, e), level=2)
            return

        for filename in files:
            file_path = child_path(path, filename)
            if not xbmcvfs.delete(file_path):
                logger.log("Download", "Failed to delete temp file: %s" % file_path, level=2)

        for dirname in dirs:
            dir_path = child_path(path, dirname)
            remove_contents(dir_path)
            if not xbmcvfs.rmdir(dir_path):
                logger.log("Download", "Failed to remove temp dir: %s" % dir_path, level=2)

    remove_contents(temp_dir)


def download_subtitles(url, provider, agents, addon, temp_dir, logger):
    _prepare_temp_dir(temp_dir, logger)

    logger.log("Download", "Download page: %s" % url, level=1)

    dl_agent = agents.get(provider) or agents.get("subhd")
    sub_name_list, short_sub_name_list, sub_file_list = dl_agent.download(url)
    logger.log("Download", "Files: %s" % sub_name_list, level=1)

    if len(sub_name_list) == 0:
        return []
    if len(sub_name_list) == 1:
        selected_sub = sub_file_list[0]
    else:
        cut_fn = addon.getSetting("cutsubfn")
        display_list = short_sub_name_list if cut_fn == "true" else sub_name_list
        sel = xbmcgui.Dialog().select("Choose Subtitle", display_list)
        if sel == -1:
            sel = 0
        selected_sub = sub_file_list[sel]

    logger.log("Download", "SUB FILE TO USE: %s" % selected_sub, level=1)
    return [selected_sub]
