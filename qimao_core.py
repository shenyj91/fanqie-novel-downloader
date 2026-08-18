# -*- coding: utf-8 -*-
"""
七猫小说核心库（聚合版封装）
============================
封装 qimao_downloader.py 的签名+AES 解密逻辑，提供与 fanqie_core 一致的接口：
- search_books(keyword) -> List[Book]
- get_directory(book_id) -> List[Chapter]
- get_chapter_content(book_id, chapter_id) -> str
- download_book(book_id, save_dir=...) -> dict

依赖：pycryptodome（pip install pycryptodome）
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from base64 import b64decode
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

try:
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import unpad
except ImportError:
    AES = None  # type: ignore

SIGN_KEY = "d3dGiJc651gSQ8w1"
AES_KEY = bytes.fromhex("32343263636238323330643730396531")
BASE_SEARCH = "https://api-bc.wtzw.com"
BASE_READ = "https://api-ks.wtzw.com"
VERSIONS = [
    "73720", "73700", "73620", "73600", "73500", "73420", "73400",
    "73328", "73325", "73320", "73300", "73220", "73200", "73100",
    "73000", "72900", "72820", "72800", "70720", "62010", "62112",
]
SOURCE_NAME = "七猫"


@dataclass
class Book:
    """统一书目模型（与 fanqie_core.Book 对齐）"""
    book_id: str
    title: str = ""
    author: str = ""
    category: str = ""
    desc: str = ""
    word_count: str = ""
    creation_status: str = ""
    source: str = SOURCE_NAME
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.creation_status == "0"


@dataclass
class Chapter:
    """统一章节模型"""
    chapter_id: str
    title: str = ""
    need_pay: int = 0
    is_locked: bool = False
    order: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


def _clean_title(s: str) -> str:
    """清洗搜索返回里的 <b>/<font> 高亮标签"""
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def sign(params: Dict[str, str]) -> str:
    keys = sorted(params.keys())
    s = "".join(f"{k}={params[k]}" for k in keys) + SIGN_KEY
    return hashlib.md5(s.encode()).hexdigest()


def stable_hash(s: str) -> int:
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    if h >= 0x80000000:
        h -= 0x100000000
    return h


def request_headers(book_id: str = "00000000") -> Dict[str, str]:
    h = stable_hash(book_id)
    idx = int(-h % len(VERSIONS)) if h < 0 else int(h % len(VERSIONS))
    hdrs = {
        "AUTHORIZATION": "",
        "app-version": VERSIONS[idx],
        "application-id": "com.****.reader",
        "channel": "unknown",
        "net-env": "1",
        "platform": "android",
        "qm-params": "",
        "reg": "0",
    }
    hdrs["sign"] = sign(hdrs)
    return hdrs


def _http_get(base: str, path: str, params: Dict[str, Any], book_id: str = "00000000", timeout: int = 25) -> Dict[str, Any]:
    params["sign"] = sign({str(k): str(v) for k, v in params.items()})
    url = base + path + "?" + urllib.parse.urlencode(params)
    hdrs = request_headers(book_id)
    hdrs["User-Agent"] = (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    )
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.URLError:
        # 证书链缺失的环境（如部分 Python 发行版）降级为不校验证书重试
        import ssl
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read()
    return json.loads(raw.decode("utf-8", "ignore"))


def _decrypt_content(encrypted_b64: str) -> str:
    if AES is None:
        raise RuntimeError("缺少 pycryptodome，请先执行: pip install pycryptodome")
    raw = b64decode(encrypted_b64)
    iv, data = raw[:16], raw[16:]
    cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=iv)
    return unpad(cipher.decrypt(data), AES.block_size).decode("utf-8")


def search_books(keyword: str, page: int = 1, per_page: int = 20) -> List[Book]:
    """关键词搜索 → 统一 Book 列表"""
    data = _http_get(BASE_SEARCH, "/search/v1/words", {
        "extend": "",
        "tab": "0",
        "gender": "0",
        "refresh_state": "8",
        "page": str(page),
        "wd": keyword,
        "is_short_story_user": "0",
    })
    books: List[Book] = []
    raw_list = (data.get("data") or {}).get("books") or []
    for b in raw_list:
        bid = b.get("id")
        if not bid:
            continue
        books.append(Book(
            book_id=str(bid),
            title=_clean_title(b.get("title", "")),
            author=b.get("author", "") or "",
            category=b.get("category_name", "") or "",
            desc=b.get("intro", "") or "",
            word_count=str(b.get("words_num", "") or ""),
            creation_status=str(b.get("is_finished", "") or ""),
            extra=b,
        ))
    return books


def get_directory(book_id: str) -> List[Chapter]:
    """目录 → 统一 Chapter 列表"""
    data = _http_get(BASE_READ, "/api/v1/chapter/chapter-list",
                     {"id": str(book_id), "chapter_ver": "0"}, str(book_id))
    chapters: List[Chapter] = []
    raw_list = (data.get("data") or {}).get("chapter_lists") or []
    for ch in raw_list:
        chapters.append(Chapter(
            chapter_id=str(ch.get("id", "")),
            title=ch.get("title", "") or "",
            order=str(ch.get("order", "") or ""),
            extra=ch,
        ))
    return chapters


def get_chapter_content(book_id: str, chapter_id: str) -> str:
    """正文（AES 解密）→ 纯文本"""
    data = _http_get(BASE_READ, "/api/v1/chapter/content",
                     {"id": str(book_id), "chapterId": str(chapter_id)}, str(book_id))
    content = (data.get("data") or {}).get("content", "")
    if not content:
        return ""
    return _decrypt_content(content)


def get_book_info(book_id: str) -> Optional[Book]:
    """按 book_id 查详情（用于还原真实书名；失败返回 None）"""
    try:
        data = _http_get(BASE_SEARCH, "/api/v4/book/detail",
                         {"id": str(book_id)}, str(book_id))
    except Exception:
        return None
    d = data.get("data") or {}
    if not d:
        return None
    # 详情实际在 data.book 里（外层 title 是占位"作品"）
    b = d.get("book") or {}
    title = _clean_title(b.get("title", "") or d.get("title", "") or "")
    if title in ("", "作品"):
        title = _clean_title(d.get("title", "") or "")
    return Book(
        book_id=str(book_id),
        title=title,
        author=b.get("author", "") or "",
        category=b.get("category_name", "") or "",
        desc=b.get("intro", "") or "",
        word_count=str(b.get("words_num", "") or ""),
        creation_status=str(b.get("is_finished", "") or ""),
        extra=b,
    )


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\r\n\t]', "", name or "").strip()
    return name[:80] or "未命名"


def download_book(
    book_id: str,
    save_dir: str = "",
    max_chapters: int = 0,
    progress_callback: Optional[Callable] = None,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """
    整本下载（七猫）。返回 {book_title, success_count, failed_count, total_count, txt_path}
    """
    import tempfile
    save_dir = save_dir or os.path.join(os.path.expanduser("~"), "Desktop", "七猫")
    os.makedirs(save_dir, exist_ok=True)

    # 书籍信息（还原书名）
    info = get_book_info(book_id)
    title = info.title if info else book_id
    author = info.author if info else ""

    chapters = get_directory(book_id)
    if max_chapters:
        chapters = chapters[:max_chapters]
    total = len(chapters)

    parts = [f"书名：{title}\n作者：{author}\n来源：七猫（原生接口）\n"]
    ok = fail = 0
    for i, ch in enumerate(chapters, 1):
        if stop_event is not None and stop_event.is_set():
            parts.append("\n[下载已停止]")
            break
        if progress_callback:
            progress_callback(i - 1, total, ch.title)
        try:
            text = get_chapter_content(book_id, ch.chapter_id)
            parts.append(f"\n\n第{i}章 {ch.title}\n{'─' * 30}\n{text}")
            ok += 1
        except Exception as e:
            parts.append(f"\n\n第{i}章 {ch.title}\n[失败: {e}]")
            fail += 1
        time.sleep(0.3)  # 限流间隔

    fname = f"{_sanitize_filename(title)}.txt"
    path = os.path.join(save_dir, fname)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))

    return {
        "book_title": title,
        "success_count": ok,
        "failed_count": fail,
        "total_count": total,
        "txt_path": path,
        "source": SOURCE_NAME,
    }


# ---- 命令行自测 ----
def _selftest() -> None:
    books = search_books("重生")
    print(f"搜索'重生' → {len(books)} 本")
    if not books:
        return
    b = books[0]
    print(f"首本: {b.book_id} | {b.title} | {b.author} | {b.word_count}字")
    chs = get_directory(b.book_id)
    print(f"章节数: {len(chs)}")
    if chs:
        text = get_chapter_content(b.book_id, chs[0].chapter_id)
        print(f"首章正文: {len(text)} 字 | 开头: {text[:60]}")


if __name__ == "__main__":
    _selftest()
