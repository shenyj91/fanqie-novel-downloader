# -*- coding: utf-8 -*-
"""
打包脚本：Windows exe 版（番茄小说全功能下载器）
在 Windows 上运行：python build_exe.py
"""
import os
import sys

def main():
    # 清理旧构建
    for d in ("build", "dist"):
        import shutil
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    opts = [
        "--onefile",
        "--windowed",
        "--name", "番茄小说下载器",
        "--clean",
        "--noconfirm",
    ]
    if os.path.exists("icon.ico"):
        opts += ["--icon", "icon.ico"]
    opts.append("gui_long.py")

    import PyInstaller.__main__
    PyInstaller.__main__.run(opts)
    print("\n完成！exe 位于 dist/番茄小说下载器.exe")


if __name__ == "__main__":
    sys.exit(main())
