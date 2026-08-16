# ChineseSubtitles

Kodi 21+ 中文字幕插件，支持从 SubHD 和 Zimuku 搜索下载字幕，自动绕过 Zimuku 的云锁验证码。

## 安装

推荐通过仓库安装以接收更新：

1. Kodi 设置 → File manager → Add source → Add network location：

        Protocol:       Web server directory (HTTPS)
        Server address: qzydustin.github.io
        Remote path:    service.subtitles.chinesesubtitles
        Port:           443

2. Add-ons → `Install from zip file` → 安装 `repository.chinesesubtitles-*.zip`。
3. `Install from repository` → `ChineseSub Repository` → 安装 ChineseSub。

也可以从[下载页面](https://qzydustin.github.io/service.subtitles.chinesesubtitles/)直接下载。

## 使用

1. 播放影片，打开字幕下载界面，选择 ChineseSubtitles。
2. 确认影视条目，选择字幕下载。
3. 若字幕包含多个文件，再选择具体使用哪个。

建议先完成刮削，确保片名、年份、季/集信息正确。

## 开发与排查

代码分两层：`resources/lib/core` 是纯 Python 字幕库（豆瓣/字幕站抓取、下载解压、过滤排序，不依赖 Kodi，可独立使用与测试）；`resources/lib/kodi` 是 Kodi 适配层（对话框、列表、设置、rar/7z 解压等 xbmc 交互）。

本插件依赖豆瓣、SubHD、Zimuku 三个外部服务，站点改版或防爬策略变化都会影响可用性。
反馈「字幕源有问题」时，可先运行健康检查定位是哪个环节：

    python3 tests/test_external_health.py          # 轻量：搜索链路 + SubHD 下载 API
    python3 tests/test_external_health.py --full   # 完整：真实下载并解压字幕

也可运行完整测试套件（联网）：`pytest tests/`。豆瓣搜索频繁调用会被限流（「搜索访问太频繁」），稍等几分钟即可恢复。

## 许可

GPL-3.0-only

## 致谢

- [svg-captcha-recognize](https://github.com/haua/svg-captcha-recognize) — 历史上的 SubHD 验证码处理启发（该形式已随站点改版移除）。
- [zimuku_for_kodi](https://github.com/pizzamx/zimuku_for_kodi) — Zimuku 站点流程参考。
- Zimuku 和 SubHD 提供的字幕资源，以及字幕作者的无偿奉献。

## 声明

本项目仅用于学习与技术研究，不存储、不分发字幕内容。如涉及侵权，请联系删除。
