# -*- coding: utf-8 -*-
"""
番茄小说 + 七猫小说 聚合下载器（macOS / Windows GUI）
====================================================
- 聚合搜索：选源（番茄 / 七猫）→ 关键词 → 列表（多选）
- 批量下载：免费 + 付费/看广告解锁章节均获取全文
- 多线程、断点缓存、进度显示
- 输出合并 TXT

运行：python3 gui_agg.py
打包：pyinstaller --onefile --windowed --name 番茄七猫聚合下载器 gui_agg.py
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qimao_core
import heiyan_core
import book88_core
from fanqie_core import download_book as fanqie_download

APP_TITLE = "番茄·七猫·黑岩·book88 聚合下载器"
APP_VERSION = "1.1.0"

SOURCES = ["番茄小说", "七猫小说", "黑岩", "book88"]


class AggGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.save_dir = str(Path.home() / "Desktop" / "聚合下载")
        self.search_items: list = []   # [(book, source), ...]
        self.page = 1
        self.stop_event = threading.Event()
        self.msg_queue = queue.Queue()
        self._build_ui()
        self._poll_queue()

    # ---------- UI ----------
    def _build_ui(self) -> None:
        self.root.title(f"{APP_TITLE} v{APP_VERSION}")
        self.root.geometry("1020x720")
        self.root.minsize(860, 560)

        top = ttk.Frame(self.root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="保存目录:").pack(side="left")
        self.save_var = tk.StringVar(value=self.save_dir)
        ttk.Entry(top, textvariable=self.save_var, width=40).pack(side="left", padx=6)
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
        self.nb.add(tab, text="聚合搜索")

        bar = ttk.Frame(tab, padding=6)
        bar.pack(fill="x")
        ttk.Label(bar, text="书源:").pack(side="left")
        self.source_var = tk.StringVar(value=SOURCES[0])
        self.source_box = ttk.Combobox(bar, textvariable=self.source_var, state="readonly", values=SOURCES, width=12)
        self.source_box.pack(side="left", padx=6)
        self.source_box.bind("<<ComboboxSelected>>", lambda e: self._on_source_change())

        # book88 平台子选择（仅 book88 源时显示）
        self.b88_label = ttk.Label(bar, text="平台:")
        self.b88_box = ttk.Combobox(bar, state="readonly", width=8,
                                    values=list(book88_core.PLATFORMS.keys()))
        self.b88_box.set("dianzhong")
        self.b88_label.pack_forget()
        self.b88_box.pack_forget()

        ttk.Label(bar, text="书名/关键词:").pack(side="left", padx=(12, 0))
        self.kw_entry = ttk.Entry(bar, width=30)
        self.kw_entry.pack(side="left", padx=6)
        self.kw_entry.bind("<Return>", lambda e: self.do_search())
        ttk.Button(bar, text="搜索", command=self.do_search).pack(side="left")
        ttk.Button(bar, text="下一页", command=self.do_search_next).pack(side="left", padx=4)

        lf = ttk.LabelFrame(tab, text="搜索结果（可多选，⌘/Ctrl+点，Shift+点，双击/回车单本下）", padding=4)
        lf.pack(fill="both", expand=True, padx=8, pady=4)
        self.search_list = tk.Listbox(
            lf,
            height=20,
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

        bottom = ttk.Frame(tab, padding=6)
        bottom.pack(fill="x")
        ttk.Button(bottom, text="⬇ 下载已选", command=self.download_selected).pack(side="left", padx=4)
        ttk.Button(bottom, text="☑ 全选", command=self._select_all).pack(side="left", padx=4)
        ttk.Button(bottom, text="☐ 反选", command=self._invert_selection).pack(side="left", padx=4)
        self.count_label = ttk.Label(bottom, text="未搜索", foreground="#888")
        self.count_label.pack(side="right", padx=8)
        ttk.Label(bottom, text="番茄/七猫/黑岩=官方直连；book88=12平台配额通道", foreground="#888").pack(side="right", padx=8)

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

    # ---------- 搜索 ----------
    def _source(self) -> str:
        return self.source_var.get()

    def _on_source_change(self) -> None:
        self.search_items = []
        self.search_list.delete(0, "end")
        self.count_label.config(text="已切换书源", foreground="#888")
        # book88 源显示平台子选择
        if self._source() == "book88":
            self.b88_label.pack(side="left", padx=(12, 0))
            self.b88_box.pack(side="left", padx=4)
        else:
            self.b88_label.pack_forget()
            self.b88_box.pack_forget()

    def _search(self, page: int) -> None:
        kw = self.kw_entry.get().strip()
        if not kw:
            messagebox.showwarning("提示", "请输入关键词")
            return
        src = self._source()
        self._set_status(f"[{src}] 搜索第 {page} 页...")
        try:
            if src == "番茄小说":
                from fanqie_core import search_books
                items = search_books(kw, page=page)
                items = [(b, "番茄小说") for b in items]
            elif src == "七猫小说":
                items = qimao_core.search_books(kw, page=page)
                items = [(b, "七猫小说") for b in items]
            elif src == "黑岩":
                items = heiyan_core.search_books(kw, page=page)
                items = [(b, "黑岩") for b in items]
            else:  # book88
                pf = self.b88_box.get() or "dianzhong"
                try:
                    quota = book88_core.get_quota()
                    self._set_status(f"[book88/{book88_core.PLATFORMS.get(pf, pf)}] 配额 {quota} | 搜索中...")
                except Exception:
                    pass
                items = book88_core.search_books(kw, page=page, platform=pf)
                items = [(b, f"book88/{book88_core.PLATFORMS.get(pf, pf)}") for b in items]
        except Exception as e:
            messagebox.showerror("搜索失败", str(e))
            return
        self.search_items = items
        self.search_list.delete(0, "end")
        for i, (b, s) in enumerate(items):
            tag = "【完结】" if getattr(b, "finished", False) else "【连载】"
            wc = getattr(b, "word_count", "") or ""
            self.search_list.insert("end", f"{i + 1}. [{s}] {b.title} | {b.author} | {b.category} | {wc}字 {tag}")
        self.count_label.config(text=f"共 {len(items)} 条（第 {page} 页）", foreground="#333")
        self._set_status(f"[{src}] 搜索完成：{len(items)} 条")

    def do_search(self) -> None:
        self.page = 1
        self._search(1)

    def do_search_next(self) -> None:
        self.page += 1
        self._search(self.page)

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
            messagebox.showwarning("提示", "请先选择书（可多选：⌘/Ctrl+点，Shift+点）")
            return
        books = [(self.search_items[i][0], self.search_items[i][1]) for i in sel]
        self._start_batch(books)

    def _start_batch(self, books: list) -> None:
        self.stop_event.clear()
        self.nb.select(self.nb.tabs()[1])  # 切到下载任务 tab
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
                if src == "番茄小说":
                    result = fanqie_download(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                elif src == "七猫小说":
                    result = qimao_core.download_book(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                elif src == "黑岩":
                    result = heiyan_core.download_book(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                    if result.get("paid_need"):
                        self.msg_queue.put(("log", f"  提示：{result['paid_need']} 章付费需黑岩账号登录(cookie)"))
                else:  # book88/平台
                    pf = getattr(b, "platform", None) or (b.extra or {}).get("platform", "dianzhong")
                    result = book88_core.download_book(
                        b.book_id,
                        save_dir=self.save_var.get(),
                        platform=pf,
                        progress_callback=lambda d, t, ch: self.msg_queue.put(("progress", (d, t))),
                        stop_event=self.stop_event,
                    )
                ok += 1
                self.msg_queue.put(("log", f"  完成：{result['success_count']}/{result['total_count']} 章 → {result['txt_path']}"))
            except Exception as e:
                fail += 1
                self.msg_queue.put(("log", f"  {b.title} 失败：{e}"))
        try:
            quota = book88_core.get_quota()
            self.msg_queue.put(("log", f"book88 剩余配额：{quota}"))
        except Exception:
            pass
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
    AggGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
