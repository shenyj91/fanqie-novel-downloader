# -*- coding: utf-8 -*-
"""
番茄小说全功能下载器（GUI）
============================
功能：
- 关键词搜索（含分页）
- 输入 book_id 直接下载整本
- 榜单浏览（分类热榜）
- 免费 + 付费（看广告解锁）章节全文下载
- 多线程下载、断点缓存、进度显示
- 输出合并 TXT（含卷名、章名）

打包：pyinstaller --onefile --windowed --name 番茄小说下载器 gui_long.py
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

# 允许从源码目录运行时导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fanqie_core import (
    FanqieClient,
    RANK_CATEGORIES,
    get_book_info,
    get_rank_list,
    search_books,
)

APP_TITLE = "番茄小说全功能下载器"
APP_VERSION = "1.0.0"


class FanqieGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.client = FanqieClient(save_dir=str(Path.home() / "Downloads"))
        self.search_items = []  # (Book, 来源说明)
        self.catalog_items = []
        self.rank_items = []
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1080x760")
        self.root.minsize(900, 600)

        # 顶栏：保存目录
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="保存目录:").pack(side="left")
        self.save_path_var = tk.StringVar(value=str(Path.home() / "Downloads"))
        ttk.Entry(top, textvariable=self.save_path_var, width=50).pack(side="left", padx=6)
        ttk.Button(top, text="浏览", command=self._choose_dir).pack(side="left")
        ttk.Button(top, text="打开目录", command=self._open_dir).pack(side="left", padx=6)

        # Notebook
        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)

        self._build_search_tab()
        self._build_rank_tab()
        self._build_direct_tab()
        self._build_download_tab()

        # 状态栏
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_search_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="搜索下载")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="关键词:").pack(side="left")
        self.search_entry = ttk.Entry(bar, width=40)
        self.search_entry.pack(side="left", padx=6)
        self.search_entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(bar, text="搜索", command=self.do_search).pack(side="left")
        ttk.Button(bar, text="下一页", command=self.do_search_next).pack(side="left", padx=4)
        self.search_page = 1

        mid = ttk.Frame(tab)
        mid.pack(fill="both", expand=True, padx=6, pady=4)

        # 左侧：搜索结果
        left = ttk.LabelFrame(mid, text="搜索结果")
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.search_list = tk.Listbox(left, height=18)
        self.search_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.search_list.bind("<Double-Button-1>", lambda e: self.load_catalog_from_search())

        # 右侧：目录
        right = ttk.LabelFrame(mid, text="章节目录（双击左侧书目加载）")
        right.pack(side="right", fill="both", expand=True, padx=(4, 0))
        self.catalog_list = tk.Listbox(right)
        self.catalog_list.pack(fill="both", expand=True, padx=4, pady=4)
        self.catalog_list.bind("<Double-Button-1>", lambda e: self.preview_chapter())

        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="下载整本（含付费章节）", command=self.download_selected_book).pack(side="left")
        ttk.Label(bottom, text="（付费/看广告解锁章节同样获取全文）", foreground="#888").pack(side="left", padx=8)

    def _build_rank_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="榜单下载")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="分类:").pack(side="left")
        self.rank_cat = ttk.Combobox(bar, state="readonly", width=14)
        names = sorted(RANK_CATEGORIES.values())
        self.rank_cat["values"] = names
        self.rank_cat.set(names[0] if names else "")
        self.rank_cat.pack(side="left", padx=6)
        ttk.Label(bar, text="性别:").pack(side="left")
        self.rank_gender = ttk.Combobox(bar, state="readonly", width=6, values=["全部", "女频", "男频"])
        self.rank_gender.set("全部")
        self.rank_gender.pack(side="left", padx=6)
        ttk.Label(bar, text="数量:").pack(side="left")
        self.rank_limit = ttk.Spinbox(bar, from_=5, to=100, width=6)
        self.rank_limit.set(20)
        self.rank_limit.pack(side="left", padx=6)
        ttk.Button(bar, text="拉取榜单", command=self.fetch_rank).pack(side="left", padx=6)

        self.rank_list = tk.Listbox(tab, height=20)
        self.rank_list.pack(fill="both", expand=True, padx=8, pady=4)
        self.rank_list.bind("<Double-Button-1>", lambda e: self.rank_download())

        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="批量下载榜单书籍（前N本）", command=self.rank_download).pack(side="left")
        ttk.Label(bottom, text="（榜单书名经平台字库混淆，下载后按真实书名保存）", foreground="#888").pack(side="left", padx=8)

    def _build_direct_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="ID直接下载")

        bar = ttk.Frame(tab, padding=10)
        bar.pack(fill="x")
        ttk.Label(bar, text="book_id / 链接:").pack(side="left")
        self.direct_entry = ttk.Entry(bar, width=55)
        self.direct_entry.pack(side="left", padx=6)
        ttk.Button(bar, text="下载整本", command=self.direct_download).pack(side="left")
        ttk.Label(
            tab,
            text="支持：纯数字 ID（如 7412557379885091902）或完整链接（https://fanqienovel.com/page/7412557379885091902）",
            foreground="#666",
        ).pack(anchor="w", padx=12)

    def _build_download_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="下载任务")

        self.task_text = tk.Text(tab, height=14, state="disabled")
        self.task_text.pack(fill="both", expand=True, padx=8, pady=8)

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, maximum=100)
        self.progress.pack(fill="x", expand=True, side="left", padx=8)
        self.progress_label = ttk.Label(bar, text="")
        self.progress_label.pack(side="right", padx=8)
        ttk.Button(bar, text="停止", command=self.stop_download).pack(side="left", padx=4)

    # ---------- 工具 ----------
    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.save_path_var.get())
        if d:
            self.save_path_var.set(d)
            self.client.save_dir = d

    def _open_dir(self) -> None:
        d = self.save_path_var.get()
        os.makedirs(d, exist_ok=True)
        if sys.platform == "darwin":
            os.system(f'open "{d}"')
        elif os.name == "nt":
            os.startfile(d)  # type: ignore
        else:
            os.system(f'xdg-open "{d}"')

    def _log(self, msg: str) -> None:
        self.task_text.configure(state="normal")
        self.task_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.task_text.see("end")
        self.task_text.configure(state="disabled")

    def _set_status(self, msg: str) -> None:
        self.status_var.set(msg)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    done, total = payload
                    self.progress["value"] = done / total * 100 if total else 0
                    self.progress_label["text"] = f"{done}/{total}"
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "done":
                    self._log(payload)
                    self._set_status("完成")
                    messagebox.showinfo("下载完成", payload)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _extract_book_id(self, text: str) -> str:
        import re
        m = re.search(r"(\d{15,})", text or "")
        return m.group(1) if m else (text or "").strip()

    # ---------- 搜索 ----------
    def _search_page(self, page: int) -> None:
        kw = self.search_entry.get().strip()
        if not kw:
            messagebox.showwarning("提示", "请输入关键词")
            return
        self._set_status(f"搜索第 {page} 页...")
        try:
            items = search_books(kw, page=page)
        except Exception as e:
            messagebox.showerror("搜索失败", str(e))
            return
        self.search_items = items
        self.search_list.delete(0, "end")
        for i, b in enumerate(items):
            tag = "【完结】" if b.finished else "【连载】"
            self.search_list.insert("end", f"{i + 1}. {b.title} | {b.author} | {b.category} {tag}")
        self._set_status(f"搜索完成：{len(items)} 条（第 {page} 页）")
        if not items:
            messagebox.showinfo("提示", "没有更多结果")

    def do_search(self) -> None:
        self.search_page = 1
        self._search_page(1)

    def do_search_next(self) -> None:
        self.search_page += 1
        self._search_page(self.search_page)

    def load_catalog_from_search(self) -> None:
        sel = self.search_list.curselection()
        if not sel:
            return
        book = self.search_items[sel[0]]
        self._load_catalog(book.book_id)

    def _load_catalog(self, book_id: str) -> None:
        self._set_status(f"拉取目录 {book_id}...")
        try:
            from fanqie_core import get_directory
            chapters, _ = get_directory(book_id)
        except Exception as e:
            messagebox.showerror("目录失败", str(e))
            return
        self.catalog_items = chapters
        self.catalog_list.delete(0, "end")
        for ch in chapters:
            lock = "🔒" if (ch.need_pay or ch.is_locked) else "  "
            self.catalog_list.insert("end", f"{lock}{ch.order:>4}. {ch.title}")
        self._set_status(f"目录共 {len(chapters)} 章")

    def preview_chapter(self) -> None:
        sel = self.catalog_list.curselection()
        if not sel:
            return
        ch = self.catalog_items[sel[0]]
        self._set_status(f"获取章节 {ch.title}...")
        threading.Thread(target=self._preview_thread, args=(ch,), daemon=True).start()

    def _preview_thread(self, ch) -> None:
        from fanqie_core import get_chapter_content
        try:
            content = get_chapter_content(ch.item_id)
            if content:
                self.msg_queue.put(("status", f"章节预览：{ch.title}（{len(content)}字）"))
                self.msg_queue.put(("log", f"【预览】{ch.title}\n{content[:200]}..."))
            else:
                self.msg_queue.put(("status", f"章节获取失败：{ch.title}"))
        except Exception as e:
            self.msg_queue.put(("log", f"预览失败：{e}"))

    # ---------- 下载 ----------
    def download_selected_book(self) -> None:
        sel = self.search_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先在搜索列表选择一本书")
            return
        book = self.search_items[sel[0]]
        self._start_download(book.book_id)

    def direct_download(self) -> None:
        bid = self._extract_book_id(self.direct_entry.get())
        if not bid:
            messagebox.showwarning("提示", "请输入 book_id 或链接")
            return
        self._start_download(bid)

    def _start_download(self, book_id: str) -> None:
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[3])  # 切到下载任务页
        self._log(f"开始下载 book_id={book_id} → {self.save_path_var.get()}")
        threading.Thread(target=self._download_thread, args=(book_id,), daemon=True).start()

    def _download_thread(self, book_id: str) -> None:
        from fanqie_core import download_book
        try:
            result = download_book(
                book_id,
                save_dir=self.save_path_var.get(),
                progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                stop_event=self.stop_event,
            )
            if result["failed_count"]:
                msg = f"完成：成功 {result['success_count']} / {result['total_count']} 章，失败 {result['failed_count']} 章"
            else:
                msg = f"完成：{result['success_count']} / {result['total_count']} 章全部成功"
            self.msg_queue.put(("log", f"输出文件：{result['txt_path']}"))
            self.msg_queue.put(("done", msg + "\n" + result["txt_path"]))
        except Exception as e:
            self.msg_queue.put(("done", f"下载失败：{e}"))

    def stop_download(self) -> None:
        self.stop_event.set()
        self._log("正在停止...（已完成章节会保留）")

    # ---------- 榜单 ----------
    def fetch_rank(self) -> None:
        cat_name = self.rank_cat.get()
        cat_id = next((k for k, v in RANK_CATEGORIES.items() if v == cat_name), 0)
        gender_map = {"全部": -1, "女频": 0, "男频": 1}
        gender = gender_map.get(self.rank_gender.get(), -1)
        try:
            limit = int(self.rank_limit.get())
        except Exception:
            limit = 20
        self._set_status(f"拉取榜单 {cat_name}...")
        try:
            books, rank_name = get_rank_list(category_id=cat_id, gender=gender, limit=limit)
            # rank/category/list 书名被字库混淆，用 book/info 还原真实书名
            from fanqie_core import get_book_info
            resolved = []
            for b in books:
                try:
                    info = get_book_info(b.book_id)
                    if info.title:
                        b.title = info.title
                    if info.author:
                        b.author = info.author
                except Exception:
                    pass
                resolved.append(b)
            books = resolved
        except Exception as e:
            messagebox.showerror("榜单失败", str(e))
            return
        self.rank_items = books
        self.rank_list.delete(0, "end")
        for i, b in enumerate(books):
            self.rank_list.insert("end", f"{i + 1:>3}. {b.title} | {b.author}")
        self._set_status(f"榜单 {rank_name or cat_name}：{len(books)} 本（真实书名已还原）")

    def rank_download(self) -> None:
        if not self.rank_items:
            messagebox.showwarning("提示", "请先拉取榜单")
            return
        books = self.rank_items
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[3])
        self._log(f"批量下载榜单 {len(books)} 本")
        threading.Thread(target=self._rank_download_thread, args=(books,), daemon=True).start()

    def _rank_download_thread(self, books) -> None:
        from fanqie_core import download_book
        total = len(books)
        for i, book in enumerate(books):
            if self.stop_event.is_set():
                self.msg_queue.put(("log", "批量下载已停止"))
                break
            self.msg_queue.put(("status", f"({i + 1}/{total}) 下载 {book.title}"))
            self.msg_queue.put(("log", f"({i + 1}/{total}) 开始：{book.title} (book_id={book.book_id})"))
            try:
                result = download_book(
                    book.book_id,
                    save_dir=self.save_path_var.get(),
                    progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                    stop_event=self.stop_event,
                )
                self.msg_queue.put(("log", f"  完成：{result['success_count']}/{result['total_count']} 章 → {result['txt_path']}"))
            except Exception as e:
                self.msg_queue.put(("log", f"  {book.title} 失败：{e}"))
        self.msg_queue.put(("done", f"批量下载结束，共 {total} 本"))


def main() -> None:
    root = tk.Tk()
    FanqieGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
