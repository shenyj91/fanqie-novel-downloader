# 番茄小说下载工具包

两个独立工具，底层共用同一套官方接口封装（`fanqie_core`）：

| 工具 | 平台 | 功能 |
|---|---|---|
| **番茄小说下载器**（gui_long.py） | Windows exe | 番茄小说全部接口：搜索、目录、ID 直下、分类榜单、整本下载（含付费/广告解锁章节） |
| **番茄短篇下载器**（gui_short.py） | macOS app | 短篇搜索、每日榜单前 20 拉取、批量下载全部章节（含付费/广告解锁） |

## 接口清单（已验证可用）

| 功能 | 接口 | 说明 |
|---|---|---|
| 搜索 | `novel.snssdk.com/api/novel/channel/homepage/search/search/v1/?q=关键词&aid=1967` | 明文返回书名/作者/分类 |
| 目录 | `fanqienovel.com/api/reader/directory/detail?bookId=xxx` | 明文，含 needPay / isChapterLock 付费标记 |
| 书籍信息 | `fanqienovel.com/api/book/info?bookId=xxx` | 书名/作者/简介明文，含 genre（8=短篇）标记 |
| 书库榜单 | `fanqienovel.com/api/author/library/book_list/v0/` | 最热 sort=0 / 最新 sort=1 / 字数 sort=2 |
| 分类榜单 | `fanqienovel.com/api/rank/category/list` | 19 个分类；bookId 明文（书名经字库混淆，下载时按真实书名落盘） |
| 短篇榜单 | 搜索热词 + genre=8 过滤（`get_short_story_rank`） | 番茄 App 书城"短篇"标签无独立公开榜单接口（App 端需签名），用"短篇/短故事/热门短篇"等热词搜索多页，过滤 genre=8 短篇标记，还原真实书名后返回前 20 |
| 正文 | 中转 `101.35.133.34:5000/api/raw_full?item_id=xxx` | **免费 + 付费（看广告解锁）章节均可获取全文** |

> 正文接口说明：官方 `/api/reader/full` 需要 X-Gorgon 等签名（web 端由 secsdk 生成，未签名时返回空）。
> 本工具通过公共中转接口获取正文，免费与付费章节都返回完整纯文本，因此「看广告解锁」的章节也能直接下载全文。

## 运行（源码方式）

```bash
cd fanqie-tools
python3 gui_long.py    # 长篇下载器（搜索/榜单/ID下载）
python3 gui_short.py   # 短篇下载器（榜单/搜索/批量）
```

仅需 Python 3.8+ 标准库，无第三方依赖。

## 打包

### Windows exe（长篇下载器）

在 Windows 上：

```bash
pip install pyinstaller
python build_exe.py
# 产出 dist/番茄小说下载器.exe
```

### macOS app（短篇下载器）

在 macOS 上：

```bash
pip install pyinstaller
python build_mac.py
# 产出 dist/番茄短篇下载器.app
# 首次打开：右键 → 打开；或 xattr -cr "dist/番茄短篇下载器.app"
```

## 使用注意

- 下载前先设置保存目录（默认 `~/Downloads` / `~/Desktop/番茄短篇`）。
- 长篇可能有上千章，建议保持默认 5 线程；若频繁失败请降低频率。
- 已下载章节会缓存在 `<保存目录>/<book_id>/.chapters/`，重下自动跳过（断点续传）。
- 榜单书名经过平台字库混淆（字体反爬），下载完成后按真实书名保存，属正常现象。
- 请勿高频请求官方接口（可能触发 IP 级风控，等待数分钟自动恢复）。

## 免责声明

本工具仅用于个人学习、备份与研究。请遵守番茄小说服务条款与相关版权法规，
勿将下载内容用于商业或侵权用途。
