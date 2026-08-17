# -*- coding: utf-8 -*-
"""
打包脚本：Windows exe 版（番茄小说全功能下载器）
在 Windows 上运行：python build_exe.py
产出：dist/番茄小说下载器.exe（中文名）
"""
import os
import shutil
import sys

# Windows 控制台默认编码可能是 cp1252/gbk，强制 UTF-8 避免中文参数报错
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    # 清理旧构建
    for d in ("build", "dist"):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    # exe 名先用 ASCII，PyInstaller 对中文 --name 在部分控制台编码下会崩
    ascii_name = "FanqieNovelDownloader"
    opts = [
        "--onefile",
        "--windowed",
        "--name", ascii_name,
        "--clean",
        "--noconfirm",
    ]
    if os.path.exists("icon.ico"):
        opts += ["--icon", "icon.ico"]
    opts.append("gui_long.py")

    import PyInstaller.__main__
    PyInstaller.__main__.run(opts)

    # 重命名为中文名
    src = os.path.join("dist", ascii_name + ".exe")
    dst = os.path.join("dist", "番茄小说下载器.exe")
    if os.path.exists(src):
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(src, dst)
        print("完成！exe 位于 dist/番茄小说下载器.exe")
    else:
        print("警告：未找到产物，请检查 dist 目录")
        print("dist 内容:", os.listdir("dist") if os.path.isdir("dist") else "dist 不存在")


if __name__ == "__main__":
    sys.exit(main())
