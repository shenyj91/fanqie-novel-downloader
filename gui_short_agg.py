# -*- coding: utf-8 -*-
"""
番茄短篇 + 七猫短篇 聚合下载器（macOS / Windows GUI）
====================================================
- 番茄短篇：关键词搜索（双通道）→ 短篇/长篇标记 → 下载全文（含付费/看广告解锁章节）
- 七猫短篇：粘贴分享链接 / bookId → 详情（书名/作者/字数/章节数/第一章免费全文）→ 下载
  （七猫短篇付费/看视频解锁章节需 App 内解锁，下载时标注）

运行：python3 gui_short_agg.py
打包：pyinstaller --onefile --windowed --name 番茄七猫短篇聚合下载器 gui_short_agg.py
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

import qimao_short_core
from fanqie_core import Book as FBook
from fanqie_core import download_book as fanqie_download
from fanqie_core import search_books as fanqie_search

APP_TITLE = "番茄·七猫 短篇聚合下载器"
APP_VERSION = "1.0.0"

SOURCES = ["番茄短篇", "七猫短篇"]


class ShortAggGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.save_dir = str(Path.home() / "Desktop" / "短篇聚合下载")
        self.search_items: list = []   # [(book, source), ...]
        self.qimao_book = None         # 七猫短篇当前加载的书
        self.page = 1
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1000x700")
        self.root.minsize(840, 560)

        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="保存目录:").pack(side="left")
        self.save_var = tk.StringVar(value=self.save_dir)
        ttk.Entry(top, textvariable=self.save_var, width=42).pack(side="left", padx=6)
        ttk.Button(top, text="浏览", command=self._choose_dir).pack(side="left")
        ttk.Button(top, text="打开", command=self._open_dir).pack(side="left", padx=4)

        self.nb = ttk.Notebook(self.root)
        self.nb.pack(fill="both", expand=True, padx=8, pady=4)

        self._build_search_tab()
        self._build_task_tab()

        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    def _build_search_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="短篇聚合")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="书源:").pack(side="left")
        self.source_var = tk.StringVar(value=SOURCES[0])
        self.source_box = ttk.Combobox(bar, textvariable=self.source_var, state="readonly", values=SOURCES, width=10)
        self.source_box.pack(side="left", padx=6)
        self.source_box.bind("<<ComboboxSelected>>", lambda e: self._on_source_change())

        self.kw_label = ttk.Label(bar, text="书名/关键词:")
        self.kw_label.pack(side="left", padx=(12, 0))
        self.kw_entry = ttk.Entry(bar, width=34)
        self.kw_entry.pack(side="left", padx=6)
        self.kw_entry.bind("<Return>", lambda e: self.do_search())
        self.btn_search = ttk.Button(bar, text="搜索", command=self.do_search)
        self.btn_search.pack(side="left")
        self.btn_next = ttk.Button(bar, text="下一页", command=self.do_search_next)
        self.btn_next.pack(side="left", padx=4)
        self.btn_load = ttk.Button(bar, text="加载短篇", command=self.do_load_share)
        # 七猫短篇提示
        self.qm_tip = ttk.Label(tab, text="", foreground="#888")

        lf = ttk.LabelFrame(tab, text="结果（可多选，⌘/Ctrl+点，Shift+点，双击/回车单本下）", padding=4)
        lf.pack(fill="both", expand=True, padx=8, pady=4)
        self.search_list = tk.Listbox(
            lf,
            height=16,
            selectmode=tk.EXTENDED,
            selectbackground="#ff5722",
            selectforeground="white",
            font=("PingFang SC", 13),
            activestyle="dotbox",
        )
        self.search_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(lf, orient="vertical", command=self.search_list.yview)
        sb.pack(side="right", fill="y")
        self.search_list.config(yscrollcommand=sb.set)
        self.search_list.bind("<Double-Button-1>", lambda e: self.download_selected())
        self.search_list.bind("<Return>", lambda e: self.download_selected())
        self.search_list.bind("<Command-a>", lambda e: self._select_all())
        self.search_list.bind("<Control-a>", lambda e: self._select_all())

        # 详情预览区（七猫短篇用）
        self.detail_text = tk.Text(tab, height=5, state="disabled", font=("PingFang SC", 11))
        self.detail_text.pack(fill="x", padx=8, pady=(0, 4))

        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="⬇ 下载已选", command=self.download_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="☑ 全选", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(bottom, text="☐ 反选", command=self._invert_selection).pack(side="left", padx=4)
        self.count_label = ttk.Label(bottom, text="", foreground="#888")
        self.count_label.pack(side="right", padx=8)

        self._on_source_change()

    def _build_task_tab(self) -> None:
        tab = ttk.Frame(self.nb)
        self.nb.add(tab, text="下载任务")

        self.log_text = tk.Text(tab, height=16, state="disabled")
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        self.progress = ttk.Progressbar(bar, maximum=100)
        self.progress.pack(fill="x", expand=True, side="left", padx=8)
        self.prog_label = ttk.Label(bar, text="")
        self.prog_label.pack(side="right", padx=8)
        ttk.Button(bar, text="停止", command=self.stop).pack(side="left", padx=4)

    # ---------- 源切换 ----------
    def _on_source_change(self) -> None:
        self.search_items = []
        self.search_list.delete(0, "end")
        self._set_detail("")
        if self._source() == "番茄短篇":
            self.kw_label.config(text="书名/关键词:")
            self.btn_search.config(text="搜索")
            self.btn_next.pack(side="left", padx=4)
            self.btn_load.pack_forget()
            self.qm_tip.config(text="")
        else:
            self.kw_label.config(text="分享链接 / bookId:")
            self.btn_search.config(text="加载")
            self.btn_next.pack_forget()
            self.btn_load.pack(side="left", padx=4)
            self.qm_tip.config(text="七猫短篇：粘贴 app-share.wtzw.com 分享链接或 bookId，加载详情后下载全文（免费+付费，走 book88 全文通道）")
            self.qm_tip.pack(anchor="w", padx=10, pady=(0, 2))
        self.count_label.config(text="")

    def _source(self) -> str:
        return self.source_var.get()

    # ---------- 搜索 / 加载 ----------
    def do_search(self) -> None:
        if self._source() == "番茄短篇":
            self.page = 1
            self._search_fanqie(1)
        else:
            self._load_qimao()

    def do_load_share(self) -> None:
        self._load_qimao()

    def do_search_next(self) -> None:
        self.page += 1
        self._search_fanqie(self.page)

    def _search_fanqie(self, page: int) -> None:
        kw = self.kw_entry.get().strip()
        if not kw:
            messagebox.showwarning("提示", "请输入关键词")
            return
        self._set_status(f"[番茄短篇] 搜索第 {page} 页...")
        try:
            items = fanqie_search(kw, page=page)
        except Exception as e:
            messagebox.showerror("搜索失败", str(e))
            return
        # 短篇优先排序（genre=8），列表标记
        items.sort(key=lambda b: 0 if getattr(b, "is_short", False) else 1)
        self.search_items = [(b, "番茄短篇") for b in items]
        self.search_list.delete(0, "end")
        short_n = 0
        for i, (b, s) in enumerate(items):
            is_short = getattr(b, "is_short", False)
            if is_short:
                short_n += 1
            tag = "【短篇】" if is_short else "【长篇】"
            fin = "【完结】" if b.finished else "【连载】"
            wc = b.word_count or ""
            self.search_list.insert("end", f"{i + 1}. {b.title} | {b.author} | {b.category} | {wc}字 {tag}{fin}")
        self.count_label.config(text=f"共 {len(items)} 条（短篇 {short_n}），第 {page} 页", foreground="#333")
        self._set_status(f"[番茄短篇] 搜索完成：{len(items)} 条（短篇 {short_n}）")

    def _load_qimao(self) -> None:
        raw = self.kw_entry.get().strip()
        if not raw:
            messagebox.showwarning("提示", "请输入七猫短篇分享链接或 bookId")
            return
        bid = qimao_short_core.parse_share_url(raw)
        if not bid:
            messagebox.showerror("解析失败", "无法识别链接格式，请粘贴 app-share.wtzw.com/.../short-story-detail/{id} 形式的链接")
            return
        self._set_status(f"[七猫短篇] 加载 {bid}...")
        try:
            book = qimao_short_core.get_book_detail(bid)
        except Exception as e:
            messagebox.showerror("加载失败", str(e))
            return
        if not book:
            messagebox.showerror("加载失败", "短篇不存在或获取失败")
            return
        self.qimao_book = book
        self.search_items = [(book, "七猫短篇")]
        self.search_list.delete(0, "end")
        tag = "【完结】" if book.finished else "【连载】"
        self.search_list.insert("end", f"1. {book.title} | {book.author} | {book.word_count}字 | {book.chapter_count}章 {tag}")
        self.count_label.config(text="共 1 本（七猫短篇）", foreground="#333")
        desc = (book.desc or "")[:120]
        self._set_detail(f"《{book.title}》 {book.author} | {book.word_count}字 | {book.chapter_count}章\n简介：{desc}\n下载将获取全文（免费+付费，走 book88 全文通道）")
        self._set_status(f"[七猫短篇] 已加载：《{book.title}》")

    def _set_detail(self, text: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        if text:
            self.detail_text.insert("end", text)
        self.detail_text.configure(state="disabled")

    # ---------- 下载 ----------
    def _select_all(self) -> None:
        self.search_list.select_set(0, "end")
        self.search_list.focus_set()

    def _invert_selection(self) -> None:
        cur = set(self.search_list.curselection())
        self.search_list.select_clear(0, "end")
        for i in range(self.search_list.size()):
            if i not in cur:
                self.search_list.select_set(i)

    def download_selected(self) -> None:
        sel = self.search_list.curselection()
        if not sel:
            messagebox.showwarning("提示", "请先选择（可多选：⌘/Ctrl+点，Shift+点）")
            return
        books = [(self.search_items[i][0], self.search_items[i][1]) for i in sel]
        self._start_batch(books)

    def _start_batch(self, books: list) -> None:
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[1])
        self._log(f"批量下载：{len(books)} 本")
        threading.Thread(target=self._batch_thread, args=(books,), daemon=True).start()

    def _batch_thread(self, books: list) -> None:
        total = len(books)
        ok = fail = 0
        for i, (b, src) in enumerate(books):
            if self.stop_event.is_set():
                self.msg_queue.put(("log", "批量下载已停止"))
                break
            self.msg_queue.put(("status", f"({i + 1}/{total}) [{src}] {b.title}"))
            self.msg_queue.put(("log", f"({i + 1}/{total}) [{src}] 下载：{b.title}"))
            try:
                if src == "番茄短篇":
                    result = fanqie_download(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                    self.msg_queue.put(("log", f"  完成：{result['success_count']}/{result['total_count']} 章 → {result['txt_path']}"))
                else:  # 七猫短篇
                    result = qimao_short_core.download_book(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                    if result.get("channel") == "book88":
                        msg = f"  完成：全文 {result['success_count']} 章（免费+付费，book88 通道）"
                    else:
                        msg = f"  完成：第一章全文，{result['paid_need']} 章付费（book88 通道不可用）"
                    self.msg_queue.put(("log", msg))
                    self.msg_queue.put(("log", f"  输出：{result['txt_path']}"))
                ok += 1
            except Exception as e:
                fail += 1
                self.msg_queue.put(("log", f"  {b.title} 失败：{e}"))
        self.msg_queue.put(("done", f"批量下载结束：成功 {ok}，失败 {fail}（共 {total} 本）"))

    # ---------- 工具 ----------
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

    def stop(self) -> None:
        self.stop_event.set()
        self._log("正在停止...（已下载章节保留）")


def main() -> None:
    root = tk.Tk()
    ShortAggGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
