# -*- coding: utf-8 -*-
"""
番茄小说官方接口核心库
========================
- 搜索：novel.snssdk.com 搜索接口（明文）
- 榜单：api/author/library/book_list/v0（最热/最新/字数）、api/rank/category/list（分类榜）
- 目录：api/reader/directory/detail（明文，含付费标记）
- 书籍信息：api/book/info
- 正文：api/reader/full 需签名，走公共中转 raw_full（免费+付费锁定章节均可获取全文）

仅用于个人学习与备份自有/公开内容，请遵守平台服务条款与版权法规。
"""

from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1"
)
UA_PC = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

API_DIRECTORY = "https://fanqienovel.com/api/reader/directory/detail"
API_BOOK_INFO = "https://fanqienovel.com/api/book/info"
API_BOOK_LIST = "https://fanqienovel.com/api/author/library/book_list/v0/"
API_RANK_CATEGORY = "https://fanqienovel.com/api/rank/category/list"
API_SEARCH = "https://novel.snssdk.com/api/novel/channel/homepage/search/search/v1/"
API_RAW_FULL = "http://101.35.133.34:5000/api/raw_full"
API_SEARCH_PROXY = "http://101.35.133.34:5000/api/search"

# 榜单分类（id: 名称）—— 来自 fanqienovel.com/rank 服务端注入
RANK_CATEGORIES: Dict[int, str] = {
    1141: "西方奇幻",
    1140: "东方仙侠",
    8: "科幻末世",
    261: "都市日常",
    124: "都市修真",
    1014: "都市高武",
    273: "历史古代",
    27: "战神赘婿",
    263: "都市种田",
    258: "传统玄幻",
    272: "历史脑洞",
    539: "悬疑脑洞",
    262: "都市脑洞",
    257: "玄幻脑洞",
    751: "悬疑灵异",
    504: "抗战谍战",
    746: "游戏体育",
    718: "动漫衍生",
    1016: "男频衍生",
}

# 榜单类型
RANK_MOLD_NEW = 1   # 新书榜
RANK_MOLD_HOT = 2   # 热榜/人气榜
RANK_MOLD_READ = 3  # 阅读榜（默认）


@dataclass
class Book:
    book_id: str
    title: str = ""
    author: str = ""
    category: str = ""
    desc: str = ""
    word_count: str = ""
    creation_status: str = ""
    thumb_url: str = ""
    score: str = ""
    genre: str = ""   # genre=8 表示短篇

    @property
    def finished(self) -> bool:
        return self.creation_status == "0"

    @property
    def is_short(self) -> bool:
        """genre=8 为短篇标记。"""
        return self.genre == "8"


@dataclass
class Chapter:
    item_id: str
    title: str = ""
    order: int = 0
    volume: str = ""
    need_pay: bool = False
    is_locked: bool = False


def _http_get(url: str, timeout: int = 20, ua: str = UA_MOBILE, referer: str = "https://fanqienovel.com/", retries: int = 3) -> str:
    headers = {
        "User-Agent": ua,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": referer,
    }
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            # 尝试解码
            for enc in ("utf-8", "gb18030", "gbk"):
                try:
                    return raw.decode(enc)
                except UnicodeDecodeError:
                    continue
            return raw.decode("utf-8", errors="ignore")
        except Exception as e:  # noqa: BLE001
            last_err = e
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败: {url[:80]}... ({last_err})")


def _json_get(url: str, timeout: int = 20, ua: str = UA_MOBILE, retries: int = 3) -> Dict[str, Any]:
    text = _http_get(url, timeout=timeout, ua=ua, retries=retries)
    return json.loads(text)


def search_books_app(keyword: str, page: int = 1, per_page: int = 20) -> List[Book]:
    """
    App 链路搜索（走公共中转 /api/search，内部调用番茄 App 搜索接口）。
    与公开接口（novel.snssdk.com）索引不完全一致——App 能搜到的书，
    公开接口有时搜不到（如《神厨老娘跟儿随军，首长香迷糊了》）。
    返回 search_tabs 综合 tab 的结果，按热度/相关度排序。
    """
    offset = (page - 1) * per_page
    url = f"{API_SEARCH_PROXY}?key={quote(keyword)}&offset={offset}"
    data = _json_get(url, timeout=25, ua=UA_MOBILE)
    books: List[Book] = []
    tabs = (data.get("data") or {}).get("search_tabs") or []
    if not tabs:
        return books
    # 综合 tab 排最前（tab_type=1）
    tab0 = tabs[0]
    items = tab0.get("data") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        bd = it.get("book_data") or []
        b = bd[0] if isinstance(bd, list) and bd else bd
        if not isinstance(b, dict):
            continue
        bid = b.get("book_id") or b.get("bookId") or ""
        if not bid:
            continue
        books.append(
            Book(
                book_id=str(bid),
                title=b.get("book_name") or b.get("title") or "",
                author=b.get("author") or "",
                category=b.get("category") or b.get("category_v2") or "",
                desc=b.get("abstract") or "",
                word_count=str(b.get("word_number") or b.get("wordNumber") or ""),
                creation_status=str(b.get("creation_status") or b.get("is_finish") or ""),
                thumb_url=b.get("thumb_url") or b.get("thumbUri") or "",
                score=str(b.get("score") or ""),
                genre=str(b.get("genre") or ""),
            )
        )
    return books


def search_books(keyword: str, page: int = 1, per_page: int = 20, fallback_app: bool = True) -> List[Book]:
    """
    关键词搜索（双通道）：
      1. 番茄公开搜索接口（novel.snssdk.com）；
      2. 若结果为空，自动切换 App 链路搜索（中转），补全 App 侧可见的书。
    page 从 1 开始；官方接口有 offset 翻页。
    """
    offset = (page - 1) * per_page
    params = {
        "q": keyword,
        "aid": "1967",
        "offset": str(offset),
        "count": str(per_page),
    }
    url = API_SEARCH + "?" + urlencode(params)
    data = _json_get(url)
    books: List[Book] = []
    ret = data.get("data", {}).get("ret_data", []) or []
    for item in ret:
        bid = item.get("book_id") or item.get("bookId") or ""
        if not bid:
            continue
        books.append(
            Book(
                book_id=str(bid),
                title=item.get("title") or item.get("book_name") or "",
                author=item.get("author") or "",
                category=item.get("category") or item.get("category_v2") or "",
                desc=item.get("abstract") or "",
                word_count=str(item.get("word_number") or item.get("wordNumber") or ""),
                creation_status=str(item.get("creation_status") or ""),
                thumb_url=item.get("thumb_url") or item.get("thumbUri") or "",
                score=str(item.get("score") or ""),
                genre=str(item.get("genre") or ""),
            )
        )
    if fallback_app and books:
        # 公开接口返回了结果，但书名没有精确命中 → 补查 App 链路，
        # 若 App 侧有精确同名书则提到最前（公开索引可能是旧名/别名）。
        exact = [b for b in books if b.title.strip() == keyword.strip()]
        if not exact:
            try:
                app_books = search_books_app(keyword, page=1, per_page=per_page)
                app_exact = [b for b in app_books if b.title.strip() == keyword.strip()]
                if app_exact:
                    exact_ids = {b.book_id for b in app_exact}
                    books = app_exact + [b for b in books if b.book_id not in exact_ids]
            except Exception:
                pass
    elif not books and fallback_app:
        try:
            books = search_books_app(keyword, page=page, per_page=per_page)
        except Exception:
            pass
    return books


def _parse_category_v2(raw: Any) -> str:
    """
    解析 book/info 的 categoryV2 字段。
    原始值是一段 JSON 数组字符串（每个元素含 Name/MainCategory），
    提取可读分类标签：主分类在前，其余标签在后，用 " / " 分隔。
    解析失败返回空串。
    """
    if not raw:
        return ""
    if isinstance(raw, str):
        s = raw.strip()
        # 可能是 JSON 数组字符串
        if s.startswith("[") or s.startswith("{"):
            try:
                data = json.loads(s)
            except Exception:
                return s
        else:
            return s
    else:
        data = raw
    items = data if isinstance(data, list) else [data]
    names: List[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = str(it.get("Name") or it.get("name") or "").strip()
        if not name or name in names:
            continue
        names.append(name)
    if not names:
        return ""
    # 主分类排最前
    def _key(it: dict) -> int:
        try:
            return 0 if it.get("MainCategory") else 1
        except Exception:
            return 1
    ordered = sorted(
        (it for it in items if isinstance(it, dict) and (it.get("Name") or it.get("name"))),
        key=_key,
    )
    out: List[str] = []
    for it in ordered:
        name = str(it.get("Name") or it.get("name") or "").strip()
        if name and name not in out:
            out.append(name)
    return " / ".join(out) if out else ""


def get_book_info(book_id: str) -> Book:
    """书籍信息（作者/简介明文，含 genre 短篇标记）。"""
    url = f"{API_BOOK_INFO}?bookId={book_id}"
    data = _json_get(url)
    d = data.get("data") or {}
    return Book(
        book_id=str(book_id),
        title=d.get("bookName") or d.get("name") or "",
        author=d.get("authorName") or d.get("author") or "",
        desc=d.get("description") or d.get("abstract") or "",
        category=_parse_category_v2(d.get("categoryV2")) or d.get("completeCategory") or "",
        thumb_url=d.get("thumbUri") or d.get("avatarUri") or "",
        word_count=str(d.get("wordNumber") or ""),
        genre=str(d.get("genre") or ""),
    )


def get_directory(book_id: str) -> Tuple[List[Chapter], Optional[Book]]:
    """获取章节目录。返回 (章节列表, 书籍信息或None)。"""
    url = f"{API_DIRECTORY}?bookId={book_id}"
    data = _json_get(url)
    d = data.get("data") or {}
    chapters: List[Chapter] = []
    for vol in d.get("chapterListWithVolume", []) or []:
        for ch in vol or []:
            chapters.append(
                Chapter(
                    item_id=str(ch.get("itemId") or ""),
                    title=ch.get("title") or "",
                    order=int(ch.get("realChapterOrder") or 0),
                    volume=ch.get("volume_name") or "",
                    need_pay=bool(ch.get("needPay")),
                    is_locked=bool(ch.get("isChapterLock")),
                )
            )
    return chapters, None


def _clean_html(text: str) -> str:
    if not text:
        return ""
    # 去除 xml/doctype 头
    text = re.sub(r"<\?xml.*?\?>", "", text, flags=re.DOTALL)
    text = re.sub(r"<!DOCTYPE.*?>", "", text, flags=re.DOTALL)
    text = re.sub(r"<html>|</html>|<head>.*?</head>|<body>|</body>", "", text, flags=re.DOTALL)
    # 标题段
    text = re.sub(r"<header>.*?</header>", "", text, flags=re.DOTALL)
    text = re.sub(r"<article>|</article>", "", text)
    text = re.sub(r"<p[^>]*>", "\n", text)
    text = re.sub(r"</p>|<br\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    # 清理作者话/注释标记
    text = re.sub(r"\{!--\s*PGC_VOICE:.*?--\}", "", text, flags=re.DOTALL)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def get_chapter_content(item_id: str, use_proxy: bool = True) -> Optional[str]:
    """
    获取章节正文。
    官方 /api/reader/full 需要签名，这里走公共中转接口 raw_full，
    免费与付费（看广告解锁）章节均可返回全文。
    返回清洗后的纯文本；失败返回 None。
    """
    if use_proxy:
        try:
            url = f"{API_RAW_FULL}?item_id={item_id}"
            data = _json_get(url, timeout=25)
            if data.get("code") == 200:
                content = (data.get("data") or {}).get("content") or ""
                cleaned = _clean_html(content)
                if cleaned:
                    return cleaned
        except Exception:
            pass
    # 兜底：官方接口（通常因签名返回空）
    try:
        url = f"https://fanqienovel.com/api/reader/full?itemId={item_id}"
        raw = _http_get(url, timeout=20)
        data = json.loads(raw)
        d = data.get("data") or {}
        content = d.get("content") or d.get("originalContent") or ""
        if isinstance(d.get("chapterData"), dict):
            content = content or d["chapterData"].get("content") or ""
        cleaned = _clean_html(content)
        if cleaned:
            return cleaned
    except Exception:
        pass
    return None


def download_book(
    book_id: str,
    save_dir: str = ".",
    max_workers: int = 5,
    delay: float = 0.3,
    callback: Optional[callable] = None,
    progress_callback: Optional[callable] = None,
    stop_event: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    下载整本小说，返回 {book, chapters, results, failed, txt_path}。
    - 免费+付费（广告解锁）章节全部尝试获取。
    - 支持断点缓存：<save_dir>/<book_id>/.chapters/NNNNN.txt
    """
    chapters, book = get_directory(book_id)
    if not chapters:
        raise RuntimeError("目录为空或获取失败")

    # 从目录接口拿不到书名时，用 book/info
    if not book or not book.title:
        try:
            book = get_book_info(book_id)
        except Exception:
            pass
    book_title = (book.title if book else "") or f"fanqie_{book_id}"
    book_title = _sanitize_filename(book_title)

    out_dir = os.path.join(save_dir, f"{book_id}")
    cache_dir = os.path.join(out_dir, ".chapters")
    os.makedirs(cache_dir, exist_ok=True)

    def _load_cache(ch: Chapter) -> Optional[str]:
        fp = os.path.join(cache_dir, f"{ch.order:05d}.txt")
        if os.path.exists(fp) and os.path.getsize(fp) > 100:
            with open(fp, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def _save_cache(ch: Chapter, content: str) -> None:
        fp = os.path.join(cache_dir, f"{ch.order:05d}.txt")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(content)

    def _download_one(ch: Chapter) -> Tuple[Chapter, Optional[str]]:
        cached = _load_cache(ch)
        if cached:
            return ch, cached
        for attempt in range(3):
            if stop_event and stop_event.is_set():
                return ch, None
            content = get_chapter_content(ch.item_id)
            if content:
                _save_cache(ch, content)
                return ch, content
            time.sleep(1 + attempt)
        return ch, None

    results: Dict[int, Tuple[Chapter, str]] = {}
    failed: List[Chapter] = []
    total = len(chapters)
    done = 0

    if total <= max_workers * 2 or max_workers <= 1:
        for ch in chapters:
            if stop_event and stop_event.is_set():
                break
            _, content = _download_one(ch)
            done += 1
            if content:
                results[ch.order] = (ch, content)
            else:
                failed.append(ch)
            if progress_callback:
                progress_callback(done, total, ch)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_download_one, ch): ch for ch in chapters}
            for fut in as_completed(futures):
                if stop_event and stop_event.is_set():
                    break
                ch, content = fut.result()
                done += 1
                if content:
                    results[ch.order] = (ch, content)
                else:
                    failed.append(ch)
                if progress_callback:
                    progress_callback(done, total, ch)
                if callback:
                    callback(ch, content)
                time.sleep(delay)

    # 合并 TXT
    txt_path = os.path.join(save_dir, f"{book_title}.txt")
    lines: List[str] = []
    lines.append(f"《{book_title}》")
    if book and book.author:
        lines.append(f"作者：{book.author}")
    if book and book.category:
        lines.append(f"分类：{book.category}")
    lines.append("")
    current_volume: Optional[str] = None
    for order in sorted(results.keys()):
        ch, content = results[order]
        if ch.volume and ch.volume != current_volume:
            current_volume = ch.volume
            lines.append("")
            lines.append(f"==== {ch.volume} ====")
            lines.append("")
        lines.append(f"{ch.title}")
        lines.append("")
        lines.append(content)
        lines.append("")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "book": book,
        "book_title": book_title,
        "chapters": chapters,
        "results": results,
        "failed": failed,
        "txt_path": txt_path,
        "success_count": len(results),
        "failed_count": len(failed),
        "total_count": total,
    }


def get_book_list(
    page_count: int = 20,
    page_index: int = 0,
    gender: int = -1,
    category_id: int = -1,
    creation_status: int = -1,
    word_count: int = -1,
    book_type: int = -1,
    sort: int = 0,
) -> List[Book]:
    """
    书库/榜单接口（最热 sort=0 / 最新 sort=1 / 字数最多 sort=2）。
    书名可能为混淆字符（字体反爬），但 book_id 为明文，可配合 get_book_info 还原。
    """
    params = {
        "page_count": page_count,
        "page_index": page_index,
        "gender": gender,
        "category_id": category_id,
        "creation_status": creation_status,
        "word_count": word_count,
        "book_type": book_type,
        "sort": sort,
    }
    url = API_BOOK_LIST + "?" + urlencode(params)
    data = _json_get(url, ua=UA_PC)
    books: List[Book] = []
    for item in data.get("data", {}).get("book_list", []) or []:
        books.append(
            Book(
                book_id=str(item.get("book_id") or ""),
                title=item.get("book_name") or "",
                author=item.get("author") or "",
                category=item.get("category") or "",
                desc=item.get("abstract") or "",
                word_count=str(item.get("word_number") or ""),
                creation_status=str(item.get("creation_status") or ""),
                thumb_url=item.get("thumb_url") or "",
            )
        )
    return books


def get_rank_list(
    category_id: int = 0,
    gender: int = -1,
    rank_mold: int = RANK_MOLD_READ,
    offset: int = 0,
    limit: int = 20,
) -> Tuple[List[Book], str]:
    """
    分类榜单（rank/category/list）。
    返回 (书籍列表, 榜单类型名称)。bookId 为明文。
    """
    params = {
        "app_id": "1967",
        "rank_list_type": "3",
        "offset": offset,
        "limit": limit,
        "rank_version": "",
        "category_id": category_id,
        "gender": gender,
        "rankMold": rank_mold,
    }
    url = API_RANK_CATEGORY + "?" + urlencode(params)
    data = _json_get(url)
    d = data.get("data") or {}
    books: List[Book] = []
    for item in d.get("book_list", []) or []:
        books.append(
            Book(
                book_id=str(item.get("bookId") or ""),
                title=item.get("bookName") or "",
                author=item.get("author") or "",
                category=item.get("categoryV2") or "",
                desc=item.get("abstract") or "",
                word_count=str(item.get("wordNumber") or ""),
                thumb_url=item.get("thumbUri") or "",
            )
        )
    rank_name = d.get("rankTypeText") or ""
    return books, rank_name


def _extract_short_from_search(keyword: str, max_pages: int = 8) -> List[Book]:
    """
    通过搜索接口获取短篇书（genre=8），多页合并去重。
    搜索接口（snssdk/中转）是唯一可直连的官方数据通道。
    """
    books: List[Book] = []
    seen: set = set()
    # 每页 10 条，搜索接口按 offset 翻页
    for page in range(max_pages):
        offset = page * 10
        url = (
            API_SEARCH
            + "?"
            + urlencode({"q": keyword, "aid": "1967", "offset": offset, "count": 10})
        )
        try:
            data = _json_get(url, timeout=20)
        except Exception:
            break
        ret = data.get("data", {}).get("ret_data", []) or []
        if not ret:
            break
        for item in ret:
            bid = str(item.get("book_id") or "")
            if not bid or bid in seen:
                continue
            seen.add(bid)
            genre = str(item.get("genre") or "")
            if genre != "8":
                continue
            books.append(
                Book(
                    book_id=bid,
                    title=item.get("title") or "",
                    author=item.get("author") or "",
                    category=item.get("category") or "",
                    desc=item.get("abstract") or "",
                    creation_status=str(item.get("creation_status") or ""),
                    thumb_url=item.get("thumb_url") or "",
                    score=str(item.get("score") or ""),
                    genre=genre,
                )
            )
        has_more = data.get("data", {}).get("has_more", False)
        if not has_more:
            break
        time.sleep(0.3)
    return books


SHORT_SEARCH_KEYWORDS = ["短篇", "短故事", "短篇小说", "热门短篇"]


def get_short_story_rank(
    limit: int = 20,
    scan_pages: int = 6,
    gender: int = -1,
    resolve_info: bool = True,
    progress_callback: Optional[callable] = None,
) -> List[Book]:
    """
    番茄短篇排行榜（基于搜索通道的实用实现）
    ==========================================
    番茄 App 书城"短篇"标签无独立公开榜单接口（App 端接口需 X-Gorgon 签名）。
    实现方式：
      1. 用"短篇 / 短故事 / 短篇小说 / 热门短篇"等热词搜索多页；
      2. 过滤 genre=8（番茄短篇标记）；
      3. 回查 book/info 还原真实书名/作者/字数；
      4. 按出现顺序（近似热度）返回前 limit 本。
    搜索结果按平台默认相关度/热度排序，短篇命中率约 40%-90%，
    多词合并后能稳定凑齐 20 本真实短篇。

    - scan_pages: 每个关键词扫描页数（每页10条）
    - gender: 保留参数（搜索接口不区分）
    - resolve_info: 是否回查 book/info 补齐信息
    """
    results: List[Book] = []
    seen: set = set()
    total_checked = 0

    for kw in SHORT_SEARCH_KEYWORDS:
        if len(results) >= limit:
            break
        try:
            batch = _extract_short_from_search(kw, max_pages=scan_pages)
        except Exception:
            continue
        for b in batch:
            total_checked += 1
            if progress_callback:
                progress_callback(total_checked)
            if b.book_id in seen:
                continue
            seen.add(b.book_id)
            if resolve_info:
                try:
                    info = get_book_info(b.book_id)
                    b.title = info.title or b.title
                    b.author = info.author or b.author
                    b.category = info.category or b.category
                    b.genre = info.genre or b.genre
                    b.word_count = info.word_count or b.word_count
                    b.thumb_url = info.thumb_url or b.thumb_url
                except Exception:
                    pass
            results.append(b)
            if len(results) >= limit:
                break
        time.sleep(0.3)

    return results


def _sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n]', "_", str(name)).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120] or "novel"


class FanqieClient:
    """面向 GUI/CLI 的封装客户端。"""

    def __init__(self, save_dir: str = "Downloads"):
        self.save_dir = save_dir

    def search(self, keyword: str, page: int = 1) -> List[Book]:
        return search_books(keyword, page=page)

    def catalog(self, book_id: str) -> List[Chapter]:
        chapters, _ = get_directory(book_id)
        return chapters

    def content(self, item_id: str) -> Optional[str]:
        return get_chapter_content(item_id)

    def download(self, book_id: str, progress_callback=None, stop_event=None) -> Dict[str, Any]:
        return download_book(
            book_id,
            save_dir=self.save_dir,
            progress_callback=progress_callback,
            stop_event=stop_event,
        )

    def rank(self, category_id: int = 0, gender: int = -1, limit: int = 20):
        return get_rank_list(category_id=category_id, gender=gender, limit=limit)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        print("== 搜索测试 ==")
        for b in search_books("小太后", page=1)[:3]:
            print(f"  {b.book_id} | {b.title} | {b.author}")
        print("== 榜单测试 ==")
        books, name = get_rank_list(category_id=261, gender=1, limit=5)
        print(f"  {name}: {len(books)} 本")
        print("== 下载测试 ==")
        result = download_book("7412557379885091902", save_dir="/tmp/fq_test")
        print(f"  成功 {result['success_count']} / {result['total_count']} 章, 输出: {result['txt_path']}")
