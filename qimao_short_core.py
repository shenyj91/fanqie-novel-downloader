# -*- coding: utf-8 -*-
"""
七猫短篇（freebook）核心库
==========================
七猫短篇走独立体系（app-share.wtzw.com/app-h5/freebook/short-story-detail/{id}）：
- 分享链接 → bookId 解析
- detail 接口：书名/作者/字数/简介/章节数 + **第一章全文**（免费试读）
- 目录接口：全部章节 id/title（含付费章节标记）
- 付费/看视频解锁章节正文需 App 内解锁，接口层拿不到（标注）

接口全部复用七猫 MD5 签名（qimao_core）。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import qimao_core

SOURCE_NAME = "七猫短篇"
SHARE_PAT = re.compile(r"short-story-detail/(\d+)")


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
    chapter_count: int = 0
    first_chapter_content: str = ""
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


def parse_share_url(url: str) -> Optional[str]:
    """从分享链接提取 bookId；支持直接传数字 bookId"""
    url = (url or "").strip()
    if url.isdigit():
        return url
    m = SHARE_PAT.search(url)
    return m.group(1) if m else None


def get_book_detail(book_id: str) -> Optional[Book]:
    """短篇详情（含第一章全文）"""
    try:
        data = qimao_core._http_get(qimao_core.BASE_SEARCH, "/api/v4/book/detail",
                                    {"id": str(book_id)}, str(book_id))
    except Exception:
        return None
    d = data.get("data") or {}
    b = d.get("book") or {}
    if not b:
        return None
    title = qimao_core._clean_title(b.get("title", "") or "")
    if not title or title == "作品":
        return None
    return Book(
        book_id=str(book_id),
        title=title,
        author=b.get("author", "") or "",
        category=(b.get("category1_name", "") or "") + " " + (b.get("category2_name", "") or ""),
        desc=b.get("intro", "") or "",
        word_count=str(b.get("words_num", "") or ""),
        creation_status="0" if b.get("is_over") else "1",
        chapter_count=int(b.get("chapters", 0) or 0),
        first_chapter_content=b.get("first_chapter_content", "") or "",
        extra=b,
    )


def get_directory(book_id: str) -> List[Chapter]:
    """短篇目录（章节列表）"""
    chapters: List[Chapter] = []
    try:
        data = qimao_core._http_get(qimao_core.BASE_READ, "/api/v1/chapter/chapter-list",
                                    {"id": str(book_id), "chapter_ver": "0"}, str(book_id))
    except Exception:
        return chapters
    raw = (data.get("data") or {}).get("chapter_lists") or []
    for ch in raw:
        chapters.append(Chapter(
            chapter_id=str(ch.get("id", "")),
            title=ch.get("title", "") or "",
            order=str(ch.get("index", "") or ch.get("chapter_sort", "") or ""),
            extra=ch,
        ))
    return chapters


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\r\n\t]', "", name or "").strip()[:80] or "未命名"


def download_book(
    book_id: str,
    save_dir: str = "",
    progress_callback: Optional[Callable] = None,
    stop_event: Any = None,
) -> Dict[str, Any]:
    """
    整本下载（七猫短篇）：
    - 第一章免费全文写入
    - 其余章节（含付费/看视频解锁）标注占位，需 App 内解锁
    返回 {book_title, success_count, paid_need, total_count, txt_path}
    """
    save_dir = save_dir or os.path.join(os.path.expanduser("~"), "Desktop", "七猫短篇")
    os.makedirs(save_dir, exist_ok=True)

    book = get_book_detail(book_id)
    if not book:
        raise RuntimeError(f"短篇不存在或获取失败: {book_id}")
    chapters = get_directory(book_id)
    total = max(len(chapters), 1)

    if progress_callback:
        progress_callback(0, total, "获取短篇信息...")

    lines = [
        f"书名：{book.title}",
        f"作者：{book.author}",
        f"字数：{book.word_count}字",
        f"来源：七猫短篇（{book_id}）",
        f"章节：共 {len(chapters)} 章（第一章免费，其余章节需 App 内观看视频/付费解锁）",
        "",
    ]
    free_ok = 0
    paid_need = 0

    # 第一章（免费全文）
    if book.first_chapter_content:
        lines.append(f"## 第1章 {book.first_chapter_content and chapters[0].title if chapters else '第一章'}\n")
        lines.append(book.first_chapter_content)
        lines.append("")
        free_ok += 1
    elif chapters:
        lines.append(f"## 第1章 {chapters[0].title}\n")
        lines.append("[第一章内容获取失败]")
        lines.append("")

    # 其余章节标注
    for i, ch in enumerate(chapters, 1):
        if i == 1:
            continue
        if stop_event is not None and stop_event.is_set():
            lines.append("\n[下载已停止]")
            break
        lines.append(f"\n## 第{i}章 {ch.title}\n")
        lines.append("[付费章节：需在七猫 App 内观看视频/付费解锁后获取全文]")
        paid_need += 1
        if progress_callback:
            progress_callback(i, total, ch.title)
        time.sleep(0.1)

    path = os.path.join(save_dir, f"{_sanitize_filename(book.title)}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return {
        "book_title": book.title,
        "success_count": free_ok,
        "paid_need": paid_need,
        "total_count": len(chapters),
        "txt_path": path,
        "source": SOURCE_NAME,
        "word_count": book.word_count,
        "desc": book.desc,
    }


def _selftest() -> None:
    for bid in ["12113751", "12794652"]:
        b = get_book_detail(bid)
        if b:
            print(f"{bid} | {b.title} | {b.author} | {b.word_count}字 | {b.chapter_count}章 | 第一章 {len(b.first_chapter_content)}字")
        else:
            print(f"{bid} 获取失败")


if __name__ == "__main__":
    _selftest()
