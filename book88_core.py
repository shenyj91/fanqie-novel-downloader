# -*- coding: utf-8 -*-
"""
book88 聚合通道核心库（聚合版封装）
==================================
封装 book88.top 第三方聚合服务（账号 zyy），一个通道覆盖 12 个平台：
  点众 / 番茄 / 七猫 / 书旗 / 头条 / 得间 / 盐言 / 掌心雷 / 蓝奏 / QQ阅读 / LOFTER / 短故事
付费全文通过 book88 配额下载（配额有限，请合理使用）。

提供与 fanqie_core 一致的接口：
- search_books(keyword, platform=...) -> List[Book]
- download_book(book_id, platform=..., save_dir=...) -> dict
"""
from __future__ import annotations

import json
import os
import re
import ssl
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SOURCE_NAME = "book88"

PLATFORMS = {
    "dianzhong": "点众", "fanqie": "番茄", "qimao": "七猫",
    "shuqi": "书旗", "toutiao": "头条", "dejian": "得间",
    "zhihu": "盐言", "zxl": "掌心雷", "lanzou": "蓝奏",
    "qq": "QQ阅读", "lofter": "LOFTER", "duanstory": "短故事",
}

BASE = "https://book88.top"
USERNAME = "zyy"
PASSWORD = "910102"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


@dataclass
class Book:
    book_id: str
    title: str = ""
    author: str = ""
    category: str = ""
    desc: str = ""
    word_count: str = ""
    creation_status: str = ""
    source: str = SOURCE_NAME
    platform: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def finished(self) -> bool:
        return self.creation_status == "0"


@dataclass
class Chapter:
    chapter_id: str
    title: str = ""
    need_pay: int = 0
    is_locked: bool = False
    order: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)


class Book88Client:
    def __init__(self, username: str = USERNAME, password: str = PASSWORD) -> None:
        self.session_cookie = ""
        self.quota = 0
        self.login(username, password)

    def _req(self, url: str, method: str = "GET", data: Optional[dict] = None) -> dict:
        headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0"}
        if self.session_cookie:
            headers["Cookie"] = self.session_cookie
        req = urllib.request.Request(url, headers=headers, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
            req.data = json.dumps(data).encode()
        with urllib.request.urlopen(req, timeout=60, context=_ssl_ctx) as r:
            return json.loads(r.read().decode("utf-8", "ignore"))

    def login(self, username: str, password: str) -> None:
        r = self._req(f"{BASE}/api/auth/login", "POST",
                      {"username": username, "password": password})
        if r.get("code") != 0:
            raise RuntimeError(f"book88 登录失败: {r}")
        # 会话 cookie
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(),
            urllib.request.HTTPSHandler(context=_ssl_ctx))
        req = urllib.request.Request(
            f"{BASE}/api/auth/login",
            data=json.dumps({"username": username, "password": password}).encode(),
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        opener.open(req, timeout=30)
        cj = None
        for h in opener.handlers:
            if isinstance(h, urllib.request.HTTPCookieProcessor):
                cj = h.cookiejar
                break
        self.session_cookie = "; ".join(f"{c.name}={c.value}" for c in cj) if cj else ""
        d = r.get("data", {})
        self.quota = d.get("remaining_quota", 0)

    def search(self, keyword: str, platform: str = "dianzhong") -> List[Book]:
        url = f"{BASE}/api/{platform}/search?keyword={urllib.parse.quote(keyword)}"
        r = self._req(url)
        data = r.get("data", {})
        raw_books = data.get("books", []) if isinstance(data, dict) else []
        books: List[Book] = []
        for bk in raw_books:
            bid = bk.get("bookId") or bk.get("book_id") or bk.get("id")
            if not bid:
                continue
            books.append(Book(
                book_id=str(bid),
                title=str(bk.get("title", "")).replace("<b>", "").replace("</b>", ""),
                author=bk.get("author", "") or "",
                category=bk.get("category_name", "") or "",
                desc=bk.get("intro", "") or "",
                word_count=str(bk.get("words_num", "") or bk.get("word_number", "") or ""),
                platform=platform,
                extra=bk,
            ))
        return books

    def download(self, book_id: str, platform: str = "dianzhong") -> tuple:
        r = self._req(f"{BASE}/api/{platform}/download?book_id={book_id}")
        d = r.get("data", {})
        if not d or not d.get("content"):
            raise RuntimeError(f"下载失败: {r.get('msg', r)}")
        title = d.get("book_name") or d.get("title") or f"book_{book_id}"
        author = d.get("author", "")
        return title, author, d.get("content", "")


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "", name or "").strip()[:80] or "未命名"


def _client() -> Book88Client:
    global _singleton
    if _singleton is None:
        _singleton = Book88Client()
    return _singleton


_singleton: Optional[Book88Client] = None


def search_books(keyword: str, page: int = 1, per_page: int = 20, platform: str = "dianzhong") -> List[Book]:
    """跨平台搜索（platform 取 PLATFORMS 的 key）"""
    return _client().search(keyword, platform)


def get_quota() -> int:
    return _client().quota


def download_book(
    book_id: str,
    save_dir: str = "",
    platform: str = "dianzhong",
    progress_callback: Optional[Callable] = None,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """整本下载（book88 通道，一次性返回全文，消耗配额）"""
    save_dir = save_dir or os.path.join(os.path.expanduser("~"), "Desktop", "book88下载")
    os.makedirs(save_dir, exist_ok=True)

    if progress_callback:
        progress_callback(0, 1, "连接 book88...")
    title, author, content = _client().download(book_id, platform)
    if stop_event is not None and stop_event.is_set():
        content = content[: content.find("\n", 1000)] + "\n[下载已停止]"

    head = f"书名：{title}\n作者：{author}\n来源：book88（{PLATFORMS.get(platform, platform)}）\n"
    path = os.path.join(save_dir, f"{_sanitize_filename(title)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(head + "=" * 50 + "\n\n" + content)
    if progress_callback:
        progress_callback(1, 1, "完成")
    return {
        "book_title": title,
        "success_count": 1 if content else 0,
        "failed_count": 0,
        "total_count": 1,
        "txt_path": path,
        "source": f"{SOURCE_NAME}({PLATFORMS.get(platform, platform)})",
    }


def _selftest() -> None:
    c = Book88Client()
    print(f"登录成功，配额 {c.quota}")
    books = c.search("将军", "dianzhong")
    print(f"[点众] 搜索'将军' → {len(books)} 本")
    if books:
        b = books[0]
        print(f"首本: {b.book_id} | {b.title} | {b.author}")


if __name__ == "__main__":
    _selftest()
