# -*- coding: utf-8 -*-
"""
黑岩小说核心库（聚合版封装）
============================
封装 heiyan.com 官方接口，提供与 fanqie_core 一致的接口：
- search_books(keyword) -> List[Book]
- get_directory(book_id) -> List[Chapter]
- get_chapter_content(book_id, chapter_id) -> dict(含 text/free/paid 标记)
- download_book(book_id, save_dir=..., cookie=...) -> dict

说明：免费章未登录即全文；付费章需登录（cookie）后已购才全文，否则标记"需登录"。
"""
from __future__ import annotations

import html as html_mod
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

SOURCE_NAME = "黑岩"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


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
    free: bool = True
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


def _http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 20) -> bytes:
    hdrs = {"User-Agent": UA, "Accept-Language": "zh-CN,zh;q=0.9"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        return e.read()
    except urllib.error.URLError:
        import ssl
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read()


def search_books(keyword: str, page: int = 1, per_page: int = 20) -> List[Book]:
    url = "https://search.heiyan.com/web/search?" + urllib.parse.urlencode({
        "queryString": keyword, "highlight": "false", "page": page})
    raw = _http_get(url)
    try:
        d = __import__("json").loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return []
    items = (d.get("data") or {}).get("content") or []
    books: List[Book] = []
    for it in items:
        bid = it.get("id")
        if not bid:
            continue
        books.append(Book(
            book_id=str(bid),
            title=it.get("name", "") or "",
            author=it.get("authorname", "") or "",
            word_count=str(it.get("words", "") or ""),
            free=bool(it.get("free")),
            desc=it.get("intro", "") or "",
            extra=it,
        ))
    return books


def get_directory(book_id: str) -> List[Chapter]:
    """目录 → [(cid, title)] 从章节页 HTML 解析"""
    url = f"https://www.heiyan.com/chapter/{book_id}"
    html_text = _http_get(url).decode("utf-8", "ignore")
    pat = re.compile(
        r'<a\s+href="https://www\.heiyan\.com/book/{bid}/{cid}"\s+class="name"\s*>\s*([^<]+?)\s*</a>'
        .format(bid=re.escape(str(book_id)), cid=r'(\d+)'), re.S)
    chapters: List[Chapter] = []
    for m in pat.finditer(html_text):
        chapters.append(Chapter(
            chapter_id=m.group(1),
            title=html_mod.unescape(m.group(2)).strip(),
        ))
    return chapters


def get_chapter_content(book_id: str, chapter_id: str) -> Dict[str, Any]:
    """返回 {text, free, paid, words, raw}；付费未登录 paid=True 且 text 为空"""
    url = f"https://a.heiyan.com/ajax/chapter/content/{chapter_id}"
    hdrs = {"Referer": f"https://www.heiyan.com/chapter/{book_id}",
            "X-Requested-With": "XMLHttpRequest"}
    raw = _http_get(url, hdrs)
    try:
        d = __import__("json").loads(raw.decode("utf-8", "ignore"))
    except Exception:
        return {"text": "", "free": False, "paid": False, "raw": raw[:200]}
    c = d.get("chapter")
    if c is None:
        if d.get("nologin"):
            return {"text": "", "free": False, "paid": True, "nologin": True}
        return {"text": "", "free": False, "paid": False, "msg": d.get("msg", "?")}
    body = _html_to_text(c.get("htmlContent", ""))
    return {"text": body, "free": bool(c.get("free")), "paid": not c.get("free"),
            "words": c.get("words", "")}


def _html_to_text(html_text: str) -> str:
    if not html_text:
        return ""
    html_text = re.sub(r'</p>', "\n", html_text, flags=re.I)
    html_text = re.sub(r'<br\s*/?>', "\n", html_text, flags=re.I)
    html_text = re.sub(r'<[^>]+>', "", html_text)
    html_text = html_mod.unescape(html_text)
    lines = [ln.strip() for ln in html_text.split("\n")]
    lines = [ln for ln in lines if ln]
    return "\n".join(lines)


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "", name or "").strip()[:80] or "未命名"


def download_book(
    book_id: str,
    save_dir: str = "",
    cookie: str = "",
    start: int = 1,
    end: int = 0,
    progress_callback: Optional[Callable] = None,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """
    整本下载（黑岩）。免费章全文；付费章无 cookie 时标记"需登录"。
    返回 {book_title, success_count, failed_count, total_count, txt_path, paid_need}
    """
    save_dir = save_dir or os.path.join(os.path.expanduser("~"), "Desktop", "黑岩")
    os.makedirs(save_dir, exist_ok=True)

    # 书名（搜索接口反查）
    title = f"book{book_id}"
    author = ""
    try:
        items = search_books(str(book_id))
        if items:
            title = items[0].title or title
            author = items[0].author or ""
    except Exception:
        pass

    chapters = get_directory(book_id)
    total = len(chapters)
    if end:
        total = min(end, total)
    ok = fail = paid_need = 0

    lines = [f"书名：{title}", f"作者：{author}", f"来源：黑岩（https://www.heiyan.com/book/{book_id}）", ""]
    for i, ch in enumerate(chapters, 1):
        if i < start or i > total:
            continue
        if stop_event is not None and stop_event.is_set():
            lines.append("\n[下载已停止]")
            break
        if progress_callback:
            progress_callback(i - start, total - start + 1, ch.title)
        try:
            r = get_chapter_content(book_id, ch.chapter_id)
            if r["text"]:
                lines.append(f"\n## {ch.title}\n\n{r['text']}")
                ok += 1
            elif r.get("paid") or r.get("nologin"):
                paid_need += 1
                lines.append(f"\n## {ch.title}\n\n[付费章节：需登录黑岩账号(cookie)后已购才可获取全文]")
            else:
                fail += 1
                lines.append(f"\n## {ch.title}\n\n[下载失败: {r.get('msg','?')}]")
        except Exception as e:
            fail += 1
            lines.append(f"\n## {ch.title}\n\n[下载失败: {e}]")
        time.sleep(0.3)

    path = os.path.join(save_dir, f"{_sanitize_filename(title)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "book_title": title,
        "success_count": ok,
        "failed_count": fail,
        "total_count": len(chapters),
        "txt_path": path,
        "source": SOURCE_NAME,
        "paid_need": paid_need,
    }


def _selftest() -> None:
    books = search_books("将军")
    print(f"搜索'将军' → {len(books)} 本")
    if not books:
        return
    b = books[0]
    print(f"首本: {b.book_id} | {b.title} | {b.author} | {b.word_count}字 | 免费={b.free}")
    chs = get_directory(b.book_id)
    print(f"章节数: {len(chs)}")
    if chs:
        r = get_chapter_content(b.book_id, chs[0].chapter_id)
        print(f"首章: {chs[0].title} | 免费={r['free']} | {len(r['text'])}字")


if __name__ == "__main__":
    _selftest()
