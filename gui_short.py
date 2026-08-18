# -*- coding: utf-8 -*-
"""
番茄短篇小说下载器（macOS GUI）
================================
功能：
- 搜索短篇小说（关键词搜索）
- 每日榜单前 20 拉取与批量下载
- 下载全部章节（含付费 / 看广告解锁章节）
- 多线程、断点缓存、进度显示
- 输出合并 TXT

打包：pyinstaller --onefile --windowed --name 番茄短篇下载器 gui_short.py
"""

from __future__ import annotations

import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fanqie_core import (
    download_book,
    get_book_info,
    get_rank_list,
    search_books,
)

APP_TITLE = "番茄短篇下载器"
APP_VERSION = "1.0.0"

# 短篇常用分类（用于榜单）
SHORT_CATEGORIES = [
    ("古风世情", 1141),
    ("都市日常", 261),
    ("悬疑脑洞", 539),
    ("都市脑洞", 262),
    ("玄幻脑洞", 257),
    ("古言脑洞", None),
    ("现言脑洞", None),
]


class ShortStoryGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.save_dir = str(Path.home() / "Desktop" / "番茄短篇")
        self.search_items = []
        self.rank_items = []
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1000x720")
        self.root.minsize(840, 560)

        # 保存目录
        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="保存目录:").pack(side="left")
        self.save_var = tk.StringVar(value=self.save_dir)
        ttk.Entry(top, textvariable=self.save_var, width=46).pack(side="left", padx=6)
        ttk.Button(top, text="浏览", command=self._choose_dir).pack(side="left")
        ttk.Button(top, text="打开", command=self._open_dir).pack(side="left", padx=4)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)

        self._build_rank_tab()
        self._build_search_tab()
        self._build_task_tab()

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    # ---- 榜单 Tab ----
    def _build_rank_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="每日榜单前20")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="榜单:").pack(side="left")
        self.rank_type = ttk.Combobox(
            bar,
            state="readonly",
            width=18,
            values=["热榜（人气）", "阅读榜", "新书榜"],
        )
        self.rank_type.set("热榜（人气）")
        self.rank_type.pack(side="left", padx=6)
        ttk.Label(bar, text="数量:").pack(side="left")
        self.rank_num = ttk.Spinbox(bar, from_=5, to=50, width=6)
        self.rank_num.set(20)
        self.rank_num.pack(side="left", padx=6)
        ttk.Button(bar, text="拉取前20榜单", command=self.fetch_rank).pack(side="left", padx=6)

        # 列表（多选 + 番茄橙高亮 + 大字）
        lf = ttk.LabelFrame(tab, text="榜单书单（可多选，⌘/Ctrl+点 多选，Shift+点 连选，双击单本下）", padding=4)
        lf.pack(fill="both", expand=True, padx=8, pady=4)
        self.rank_list = tk.Listbox(
            lf,
            height=18,
            selectmode=tk.EXTENDED,
            selectbackground="#ff5722",
            selectforeground="white",
            font=("PingFang SC", 13),
            activestyle="dotbox",
        )
        self.rank_list.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.rank_list.yview)
        sb.pack(side="right", fill="y")
        self.rank_list.config(yscrollcommand=sb.set)
        self.rank_list.bind("<Double-Button-1>", lambda e: self.download_selected_rank())
        self.rank_list.bind("<Return>", lambda e: self.download_selected_rank())
        self.rank_list.bind("<Command-a>", lambda e: self._select_all(self.rank_list))
        self.rank_list.bind("<Control-a>", lambda e: self._select_all(self.rank_list))

        # 底部按钮（更醒目）
        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="⬇ 下载已选", command=self.download_selected_rank).pack(side="left", padx=4)
        ttk.Button(bottom, text="☑ 全选", command=lambda: self._select_all(self.rank_list)).pack(side="left", padx=4)
        ttk.Button(bottom, text="☐ 反选", command=lambda: self._invert_selection(self.rank_list)).pack(side="left", padx=4)
        ttk.Button(bottom, text="⬇ 全部下载", command=self.download_all_rank).pack(side="left", padx=4)
        self.rank_count_label = ttk.Label(bottom, text="未加载", foreground="#888")
        self.rank_count_label.pack(side="right", padx=8)

        tip = ttk.Label(
            tab,
            text="说明：榜单返回的书名经平台字库混淆，下载时按真实书名保存。含付费/看广告解锁章节，均获取全文。",
            foreground="#666",
        )
        tip.pack(anchor="w", padx=10, pady=(0, 6))

    # ---- 搜索 Tab ----
    def _build_search_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="搜索短篇")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="书名/关键词:").pack(side="left")
        self.kw_entry = ttk.Entry(bar, width=40)
        self.kw_entry.pack(side="left", padx=6)
        self.kw_entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(bar, text="搜索", command=self.do_search).pack(side="left")
        ttk.Button(bar, text="下一页", command=self.do_search_next).pack(side="left", padx=4)
        self.page = 1

        # 列表（多选 + 番茄橙高亮 + 大字）
        lf = ttk.LabelFrame(tab, text="搜索结果（可多选，⌘/Ctrl+点 多选，Shift+点 连选，双击/回车单本下）", padding=4)
        lf.pack(fill="both", expand=True, padx=8, pady=4)
        self.search_list = tk.Listbox(
            lf,
            height=18,
            selectmode=tk.EXTENDED,
            selectbackground="#ff5722",
            selectforeground="white",
            font=("PingFang SC", 13),
            activestyle="dotbox",
        )
        self.search_list.pack(fill="both", expand=True, side="left")
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.search_list.yview)
        sb.pack(side="right", fill="y")
        self.search_list.config(yscrollcommand=sb.set)
        self.search_list.bind("<Double-Button-1>", lambda e: self.download_selected_search())
        self.search_list.bind("<Return>", lambda e: self.download_selected_search())
        self.search_list.bind("<Command-a>", lambda e: self._select_all(self.search_list))
        self.search_list.bind("<Control-a>", lambda e: self._select_all(self.search_list))

        # 底部按钮（更醒目）
        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="⬇ 下载已选", command=self.download_selected_search).pack(side="left", padx=4)
        ttk.Button(bottom, text="☑ 全选", command=lambda: self._select_all(self.search_list)).pack(side="left", padx=4)
        ttk.Button(bottom, text="☐ 反选", command=lambda: self._invert_selection(self.search_list)).pack(side="left", padx=4)
        self.search_count_label = ttk.Label(bottom, text="未搜索", foreground="#888")
        self.search_count_label.pack(side="right", padx=8)

    # ---- 任务 Tab ----
    def _build_task_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="下载任务")

        self.log_text = tk.Text(tab, height=14, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, maximum=100)
        self.progress.pack(fill="x", expand=True, side="left", padx=8)
        self.prog_label = ttk.Label(bar, text="")
        self.prog_label.pack(side="right", padx=8)
        ttk.Button(bar, text="停止", command=self.stop).pack(side="left", padx=4)

    # ---- 工具 ----
    def _choose_dir(self) -> None:
        d = filedialog.askdirectory(initialdir=self.save_var.get())
        if d:
            self.save_var.set(d)

    def _open_dir(self) -> None:
        d = self.save_var.get()
        os.makedirs(d, exist_ok=True)
        if sys.platform == "darwin":
            os.system(f'open "{d}"')

    def _log(self, msg: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

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
                    self.prog_label["text"] = f"{done}/{total}"
                elif kind == "status":
                    self._set_status(payload)
                elif kind == "done":
                    self._log(payload)
                    self._set_status("完成")
                    messagebox.showinfo("完成", payload)
        except queue.Empty:
            pass
        self.root.after(200, self._poll_queue)

    def _bid(self, text: str) -> str:
        m = re.search(r"(\d{15,})", text or "")
        return m.group(1) if m else (text or "").strip()

    # ---- 榜单 ----
    def fetch_rank(self) -> None:
        try:
            limit = int(self.rank_num.get())
        except Exception:
            limit = 20
        self._set_status("拉取短篇榜单（扫描热榜并筛选短篇）...")
        try:
            from fanqie_core import get_short_story_rank
            # 并行扫描热榜页数，按 limit 需求动态扩展扫描深度
            scan_pages = max(3, min(10, limit // 3 + 2))
            self.rank_items = get_short_story_rank(
                limit=limit,
                scan_pages=scan_pages,
                progress_callback=lambda n: self._set_status(f"扫描热榜中…已检查 {n} 本"),
            )
            rank_name = "番茄短篇热榜（按热度筛选短篇）"
        except Exception as e:
            messagebox.showerror("榜单失败", str(e))
            return
        self.rank_list.delete(0, "end")
        for i, b in enumerate(self.rank_items):
            wc = b.word_count or "?"
            self.rank_list.insert("end", f"{i + 1:>3}. {b.title} | {b.author} | {b.category} | {wc}字")
        self.rank_count_label.config(text=f"共 {len(self.rank_items)} 本", foreground="#333")
        self._set_status(f"{rank_name}：{len(self.rank_items)} 本（真实书名已还原）")

    def _start_download(self, book_id: str, title: str = "") -> None:
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[2])
        self._log(f"开始下载：{title or book_id} (book_id={book_id})")
        threading.Thread(target=self._dl_thread, args=(book_id, title), daemon=True).start()

    def _dl_thread(self, book_id: str, title: str = "") -> None:
        try:
            result = download_book(
                book_id,
                save_dir=self.save_var.get(),
                progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                stop_event=self.stop_event,
            )
            msg = f"《{result['book_title']}》：成功 {result['success_count']}/{result['total_count']} 章"
            if result["failed_count"]:
                msg += f"，失败 {result['failed_count']} 章"
            self.msg_queue.put(("log", f"  输出：{result['txt_path']}"))
            self.msg_queue.put(("done", msg))
        except Exception as e:
            self.msg_queue.put(("done", f"下载失败：{e}"))

    def _select_all(self, lb: tk.Listbox) -> None:
        lb.select_set(0, "end")
        lb.focus_set()

    def _invert_selection(self, lb: tk.Listbox) -> None:
        cur = set(lb.curselection())
        lb.select_clear(0, "end")
        for i in range(lb.size()):
            if i not in cur:
                lb.select_set(i)

    def _download_books(self, books: list, tag: str = "下载") -> None:
        """把选中或全部的书加入下载队列（后台批量）"""
        if not books:
            messagebox.showwarning("提示", "列表为空")
            return
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[2])  # 切到下载任务 tab
        self._log(f"批量{tag}：{len(books)} 本")
        threading.Thread(target=self._batch_thread, args=(books, tag), daemon=True).start()

    def _batch_thread(self, books, tag: str) -> None:
        total = len(books)
        ok = fail = 0
        for i, b in enumerate(books):
            if self.stop_event.is_set():
                self.msg_queue.put(("log", "批量下载已停止"))
                break
            self.msg_queue.put(("status", f"({i + 1}/{total}) {b.title}"))
            self.msg_queue.put(("log", f"({i + 1}/{total}) {tag}：{b.title}"))
            try:
                result = download_book(
                    b.book_id,
                    save_dir=self.save_var.get(),
                    progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                    stop_event=self.stop_event,
                )
                ok += 1
                self.msg_queue.put(("log", f"  完成：{result['success_count']}/{result['total_count']} 章 → {result['txt_path']}"))
            except Exception as e:
                fail += 1
                self.msg_queue.put(("log", f"  {b.title} 失败：{e}"))
        self.msg_queue.put(("done", f"批量{tag}结束：成功 {ok}，失败 {fail}（共 {total} 本）"))

    # ---- 搜索 ----
    def _search(self, page: int) -> None:
        kw = self.kw_entry.get().strip()
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
        self.search_count_label.config(text=f"共 {len(items)} 条（第 {page} 页）", foreground="#333")
        self._set_status(f"搜索完成：{len(items)} 条（第 {page} 页）")

    def do_search(self) -> None:
        self.page = 1
        self._search(1)

    def do_search_next(self) -> None:
        self.page += 1
        self._search(self.page)

    def download_selected_rank(self) -> None:
        sel = self.rank_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先在榜单列表选择书（可多选：⌘/Ctrl+点，Shift+点）")
            return
        books = [self.rank_items[i] for i in sel]
        self._download_books(books, tag=f"榜单下载({len(books)}本)")

    def download_all_rank(self) -> None:
        if not self.rank_items:
            messagebox.showwarning("提示", "请先拉取榜单")
            return
        if not messagebox.askyesno("确认", f"将批量下载榜单全部 {len(self.rank_items)} 本，是否继续？"):
            return
        self._download_books(list(self.rank_items), tag=f"榜单全量({len(self.rank_items)}本)")

    def download_selected_search(self) -> None:
        sel = self.search_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择书（可多选：⌘/Ctrl+点，Shift+点）")
            return
        books = [self.search_items[i] for i in sel]
        if len(books) == 1:
            self._start_download(books[0].book_id, books[0].title)
        else:
            self._download_books(books, tag=f"搜索下载({len(books)}本)")

    def stop(self) -> None:
        self.stop_event.set()
        self._log("正在停止...（已下载章节保留）")


def main() -> None:
    root = tk.Tk()
    ShortStoryGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
