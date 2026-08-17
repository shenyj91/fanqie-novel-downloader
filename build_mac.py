# -*- coding: utf-8 -*-
"""
打包脚本：macOS .app 版（番茄短篇下载器）
在 macOS 上运行：python build_mac.py
产出：dist/番茄短篇下载器.app
"""
import os
import shutil
import sys

def main():
    for d in ("build", "dist"):
        if os.path.exists(d):
            shutil.rmtree(d, ignore_errors=True)

    opts = [
        "--onefile",
        "--windowed",
        "--name", "番茄短篇下载器",
        "--clean",
        "--noconfirm",
        "--osx-bundle-identifier", "com.syj.fanqie-short",
    ]
    if os.path.exists("icon.icns"):
        opts += ["--icon", "icon.icns"]
    opts.append("gui_short.py")

    import PyInstaller.__main__
    PyInstaller.__main__.run(opts)
    print("\n完成！app 位于 dist/番茄短篇下载器.app")


if __name__ == "__main__":
    sys.exit(main())
