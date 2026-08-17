# -*- coding: utf-8 -*-
"""番茄小说官方接口封装（搜索/榜单/目录/正文/下载）。"""

from .core import (
    FanqieClient,
    Book,
    Chapter,
    search_books,
    search_books_app,
    get_book_info,
    get_directory,
    get_chapter_content,
    download_book,
    get_book_list,
    get_rank_list,
    get_short_story_rank,
    RANK_CATEGORIES,
)

__all__ = [
    "FanqieClient",
    "Book",
    "Chapter",
    "search_books",
    "search_books_app",
    "get_book_info",
    "get_directory",
    "get_chapter_content",
    "download_book",
    "get_book_list",
    "get_rank_list",
    "get_short_story_rank",
    "RANK_CATEGORIES",
]

__version__ = "1.0.0"
